import json
import re
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterator
from unittest.mock import Mock, patch, sentinel

import pytest
from clickhouse_driver import Client

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import (
    ClickhouseCluster,
    HostInfo,
    MutationNotFound,
    AlterTableMutationRunner,
    LightweightDeleteMutationRunner,
    T,
    MutationWaiter,
    Query,
    RetryPolicy,
    get_cluster,
)
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.test.base import materialized


@pytest.fixture
def cluster(django_db_setup) -> Iterator[ClickhouseCluster]:
    yield get_cluster()


def test_mutation_runner_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError):
        AlterTableMutationRunner("table", {"command"}, parameters={"__invalid_key": True})


def test_exception_summary(snapshot, cluster: ClickhouseCluster) -> None:
    def replace_memory_addresses_and_ips(value):
        message = re.sub(r"0x[0-9A-Fa-f]{16}", "0x0000000000000000", value)
        return re.sub(r"address='\d{1,3}.\d{1,3}.\d{1,3}.\d{1,3}'", "address='127.0.0.1'", message)

    with pytest.raises(ExceptionGroup) as e:
        cluster.map_all_hosts(Query("invalid query")).result()

    assert replace_memory_addresses_and_ips(e.value.message) == snapshot

    with pytest.raises(ExceptionGroup) as e:
        cluster.map_all_hosts(Query("SELECT * FROM invalid_table_name")).result()

    assert replace_memory_addresses_and_ips(e.value.message) == snapshot

    with pytest.raises(ExceptionGroup) as e:

        def explode(_):
            raise ValueError("custom error")

        cluster.map_all_hosts(explode).result()

    assert replace_memory_addresses_and_ips(e.value.message) == snapshot


def test_retry_policy():
    policy = RetryPolicy(max_attempts=2, delay=0)

    # happy function, should not be retried
    happy_function = Mock(side_effect=[sentinel.RESULT])
    task = policy(happy_function)
    assert task(Mock()) is sentinel.RESULT
    assert happy_function.call_count == 1

    # flaky function, should be retried
    flaky_function = Mock(side_effect=[Exception(), sentinel.RESULT])
    task = policy(flaky_function)
    assert task(Mock()) is sentinel.RESULT
    assert flaky_function.call_count == 2

    # angry function, always fails and should retry up to max
    angry_function = Mock(side_effect=Exception(sentinel.ERROR))
    task = policy(angry_function)
    with pytest.raises(Exception) as e:
        task(Mock())

    assert e.value.args == (sentinel.ERROR,)
    assert angry_function.call_count == 2

    # function that throws a surprising non-retryable error should not be retried
    surprising_function = Mock(side_effect=Exception(sentinel.ERROR))
    task = RetryPolicy(max_attempts=2, delay=0, exceptions=(ValueError,))(surprising_function)
    with pytest.raises(Exception) as e:
        task(Mock())

    assert e.value.args == (sentinel.ERROR,)
    assert surprising_function.call_count == 1


def test_retry_policy_exception_test():
    retryable_exception = Exception(sentinel.RETRYABLE)
    policy = RetryPolicy(max_attempts=2, delay=0, exceptions=lambda e: e == retryable_exception)

    retryable_callable = Mock(side_effect=retryable_exception)
    task = policy(retryable_callable)
    with pytest.raises(Exception) as e:
        task(Mock())

    assert e.value == retryable_exception
    assert retryable_callable.call_count == policy.max_attempts

    non_retryable_exception = Exception(sentinel.NON_RETRYABLE)
    non_retryable_callable = Mock(side_effect=non_retryable_exception)
    task = policy(non_retryable_callable)
    with pytest.raises(Exception) as e:
        task(Mock())

    assert e.value == non_retryable_exception
    assert non_retryable_callable.call_count == 1


def test_alter_mutation_single_command(cluster: ClickhouseCluster) -> None:
    table = EVENTS_DATA_TABLE()
    count = 100

    # make sure there is some data to play with first
    def populate_random_data(client: Client) -> None:
        client.execute(f"INSERT INTO {table} SELECT * FROM generateRandom() LIMIT {count}")

    cluster.map_one_host_per_shard(populate_random_data).result()

    # construct the runner
    sentinel_uuid = uuid.uuid1()  # unique to this test run to ensure we have a clean slate
    runner = AlterTableMutationRunner(
        table,
        {
            """
            UPDATE person_id = %(uuid)s, properties = %(properties)s
            -- this is a comment that will not appear in system.mutations
            WHERE 1 = /* this will also be stripped out during formatting */ 01
            """
        },
        parameters={"uuid": sentinel_uuid, "properties": json.dumps({"uuid": sentinel_uuid.hex})},
    )

    # nothing should be running yet
    existing_mutations = cluster.map_all_hosts(runner._find).result()
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

    with pytest.raises(MutationNotFound):
        assert cluster.any_host(MutationWaiter("x", {"y"}).is_done).result()


def test_alter_mutation_multiple_commands(cluster: ClickhouseCluster) -> None:
    table = EVENTS_DATA_TABLE()
    count = 100

    # make sure there is some data to play with first
    def populate_random_data(client: Client) -> None:
        client.execute(f"INSERT INTO {table} SELECT * FROM generateRandom() LIMIT {count}")

    cluster.map_one_host_per_shard(populate_random_data).result()

    sentinel_uuid = uuid.uuid1()  # unique to this test run to ensure we have a clean slate

    with (
        materialized("events", f"{sentinel_uuid}_a") as column_a,
        materialized("events", f"{sentinel_uuid}_b") as column_b,
    ):
        runner = AlterTableMutationRunner(
            table,
            {f"MATERIALIZE COLUMN {column_a.name}", f"MATERIALIZE COLUMN {column_b.name}"},
        )

        # nothing should be running yet
        existing_mutations = cluster.map_all_hosts(runner._find).result()
        assert all(mutation is None for mutation in existing_mutations.values())

        # start all mutations
        shard_mutations = cluster.map_one_host_per_shard(runner.enqueue).result()
        assert len(shard_mutations) > 0

        for host_info, mutation in shard_mutations.items():
            assert host_info.shard_num is not None

            # wait for mutations to complete on shard
            cluster.map_all_hosts_in_shard(host_info.shard_num, mutation.wait).result()

            # check to make sure all mutations are marked as done
            assert all(cluster.map_all_hosts_in_shard(host_info.shard_num, mutation.is_done).result().values())


def test_map_hosts_by_role() -> None:
    bootstrap_client_mock = Mock()
    bootstrap_client_mock.execute = Mock()
    bootstrap_client_mock.execute.return_value = [
        ("host1", "9000", "1", "1", "online", "data"),
        ("host2", "9000", "1", "2", "online", "data"),
        ("host3", "9000", "1", "3", "online", "data"),
        ("host4", "9000", "1", "4", "online", "coordinator"),
    ]

    cluster = ClickhouseCluster(bootstrap_client_mock)

    times_called: defaultdict[NodeRole, int] = defaultdict(int)

    def mock_get_task_function(_, host: HostInfo, fn: Callable[[Client], T]) -> Callable[[], T]:
        if host.host_cluster_role == NodeRole.DATA.value.lower():
            times_called[NodeRole.DATA] += 1
        elif host.host_cluster_role == NodeRole.COORDINATOR.value.lower():
            times_called[NodeRole.COORDINATOR] += 1
        return lambda: fn(Mock())

    with patch.object(ClickhouseCluster, "_ClickhouseCluster__get_task_function", mock_get_task_function):
        cluster.map_hosts_by_role(lambda _: (), node_role=NodeRole.DATA).result()
        assert times_called[NodeRole.DATA] == 3
        assert times_called[NodeRole.COORDINATOR] == 0
        times_called.clear()

        cluster.map_hosts_by_role(lambda _: (), node_role=NodeRole.COORDINATOR).result()
        assert times_called[NodeRole.DATA] == 0
        assert times_called[NodeRole.COORDINATOR] == 1
        times_called.clear()

        cluster.map_hosts_by_role(lambda _: (), node_role=NodeRole.ALL).result()
        assert times_called[NodeRole.DATA] == 3
        assert times_called[NodeRole.COORDINATOR] == 1


def test_lightweight_delete(cluster: ClickhouseCluster) -> None:
    table = EVENTS_DATA_TABLE()
    count = 100

    def truncate_table(client: Client) -> None:
        client.execute(f"TRUNCATE TABLE {table}")

    cluster.map_one_host_per_shard(truncate_table).result()

    # make sure there is some data to play with first
    def populate_random_data(client: Client) -> None:
        client.execute(f"INSERT INTO {table} SELECT * FROM generateRandom() LIMIT {count}")

    cluster.map_one_host_per_shard(populate_random_data).result()

    def get_random_row(client: Client) -> list[tuple[uuid.UUID]]:
        return client.execute(f"SELECT uuid FROM {table} ORDER BY rand() LIMIT 1")

    [[[eid]]] = cluster.map_all_hosts(get_random_row).result().values()

    # construct the runner with a DELETE command
    runner = LightweightDeleteMutationRunner(
        table,
        f"uuid = %(uuid)s",
        parameters={"uuid": eid},
    )

    # start all mutations
    shard_mutations = cluster.map_one_host_per_shard(runner.enqueue).result()
    assert len(shard_mutations) > 0

    # check results
    def get_row_exists_count(client: Client) -> list[tuple[int]]:
        return client.execute(f"SELECT count(1) FROM {table}")

    for host_info, mutation in shard_mutations.items():
        assert host_info.shard_num is not None

        # wait for mutations to complete on shard
        cluster.map_all_hosts_in_shard(host_info.shard_num, mutation.wait).result()

        # check to make sure all mutations are marked as done
        assert all(cluster.map_all_hosts_in_shard(host_info.shard_num, mutation.is_done).result().values())

        # check to ensure data is as expected to be after update (fewer rows visible than initially created)
        query_results = cluster.map_all_hosts_in_shard(host_info.shard_num, get_row_exists_count).result()
        assert all(result[0][0] < count for result in query_results.values())
