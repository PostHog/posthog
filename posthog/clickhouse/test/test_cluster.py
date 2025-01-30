from collections import defaultdict
from unittest.mock import Mock, patch
import uuid
from collections.abc import Callable, Iterator

import pytest
from clickhouse_driver import Client

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import T, ClickhouseCluster, ConnectionInfo, HostInfo, MutationRunner, get_cluster
from posthog.models.event.sql import EVENTS_DATA_TABLE


@pytest.fixture
def cluster(django_db_setup) -> Iterator[ClickhouseCluster]:
    yield get_cluster()


def test_mutations(cluster: ClickhouseCluster) -> None:
    table = EVENTS_DATA_TABLE()
    count = 100

    # make sure there is some data to play with first
    def populate_random_data(client: Client) -> None:
        client.execute(f"INSERT INTO {table} SELECT * FROM generateRandom() LIMIT {count}")

    cluster.map_one_host_per_shard(populate_random_data).result()

    # construct the runner
    sentinel_uuid = uuid.uuid1()  # unique to this test run to ensure we have a clean slate
    runner = MutationRunner(
        table,
        f"""
        UPDATE person_id = %(uuid)s
        -- this is a comment that will not appear in system.mutations
        WHERE 1 = /* this will also be stripped out during formatting */ 01
        """,
        {"uuid": sentinel_uuid},
    )

    # nothing should be running yet
    existing_mutations = cluster.map_all_hosts(runner.find).result()
    assert all(mutation is None for mutation in existing_mutations.values())

    # start all mutations
    shard_mutations = cluster.map_one_host_per_shard(runner.enqueue).result()
    assert len(shard_mutations) > 0

    # check results
    def get_person_ids(client: Client) -> list[tuple[uuid.UUID, int]]:
        return client.execute(f"SELECT person_id, count() FROM {table} GROUP BY ALL ORDER BY ALL")

    for host_info, mutation in shard_mutations.items():
        assert host_info.shard_num is not None

        # wait for mutations to complete on shard
        cluster.map_all_hosts_in_shard(host_info.shard_num, mutation.wait).result()

        # check to make sure all mutations are marked as done
        assert all(cluster.map_all_hosts_in_shard(host_info.shard_num, mutation.is_done).result().values())

        # check to ensure data is as expected to be after update
        query_results = cluster.map_all_hosts_in_shard(host_info.shard_num, get_person_ids).result()
        assert all(result == [(sentinel_uuid, count)] for result in query_results.values())

    # submitting a duplicate mutation should just return the original and not schedule anything new
    def get_mutations_count(client: Client) -> int:
        [[result]] = client.execute("SELECT count() FROM system.mutations")
        return result

    mutations_count_before = cluster.map_all_hosts(get_mutations_count).result()

    duplicate_mutations = cluster.map_one_host_per_shard(runner.enqueue).result()
    assert shard_mutations == duplicate_mutations

    assert cluster.map_all_hosts(get_mutations_count).result() == mutations_count_before


def test_map_all_hosts_filter_by_node_role(cluster: ClickhouseCluster) -> None:
    hosts_info = [
        HostInfo(
            ConnectionInfo(address="host1", port=9000),
            shard_num=1,
            replica_num=1,
            host_cluster_role="worker",
            host_cluster_type="online",
        ),
        HostInfo(
            ConnectionInfo(address="host2", port=9000),
            shard_num=1,
            replica_num=2,
            host_cluster_role="worker",
            host_cluster_type="online",
        ),
        HostInfo(
            ConnectionInfo(address="host3", port=9000),
            shard_num=1,
            replica_num=3,
            host_cluster_role="worker",
            host_cluster_type="online",
        ),
        HostInfo(
            ConnectionInfo(address="host4", port=9000),
            shard_num=1,
            replica_num=4,
            host_cluster_role="coordinator",
            host_cluster_type="online",
        ),
    ]
    cluster._ClickhouseCluster__hosts = hosts_info

    times_called = defaultdict(int)

    def mock_get_task_function(_, host: HostInfo, fn: Callable[[Client], T]) -> Callable[[], T]:
        if host.host_cluster_role == NodeRole.WORKER.value.lower():
            times_called[NodeRole.WORKER] += 1
        elif host.host_cluster_role == NodeRole.COORDINATOR.value.lower():
            times_called[NodeRole.COORDINATOR] += 1
        return lambda: fn(Mock())

    with patch.object(ClickhouseCluster, "_ClickhouseCluster__get_task_function", mock_get_task_function):
        cluster.map_all_hosts(lambda _: (), node_role=NodeRole.WORKER).result()
        assert times_called[NodeRole.WORKER] == 3
        assert times_called[NodeRole.COORDINATOR] == 0
        times_called.clear()

        cluster.map_all_hosts(lambda _: (), node_role=NodeRole.COORDINATOR).result()
        assert times_called[NodeRole.WORKER] == 0
        assert times_called[NodeRole.COORDINATOR] == 1
        times_called.clear()

        cluster.map_all_hosts(lambda _: (), node_role=NodeRole.ALL).result()
        assert times_called[NodeRole.WORKER] == 3
        assert times_called[NodeRole.COORDINATOR] == 1
