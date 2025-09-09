import re
import json
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping

import pytest
from posthog.test.base import materialized
from unittest.mock import Mock, patch, sentinel

from clickhouse_driver import Client

from posthog.clickhouse.client.connection import NodeRole, Workload
from posthog.clickhouse.cluster import (
    AlterTableMutationRunner,
    ClickhouseCluster,
    HostInfo,
    LightweightDeleteMutationRunner,
    MutationNotFound,
    MutationWaiter,
    Query,
    RetryPolicy,
    T,
    get_cluster,
)
from posthog.models.event.sql import EVENTS_DATA_TABLE


@pytest.fixture
def cluster(django_db_setup) -> Iterator[ClickhouseCluster]:
    yield get_cluster()


def test_mutation_runner_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError):
        AlterTableMutationRunner(table="table", commands={"command"}, parameters={"__invalid_key": True})


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


def wait_and_check_mutations_on_shards(
    cluster: ClickhouseCluster, shard_mutations: Mapping[HostInfo, MutationWaiter]
) -> None:
    assert len(shard_mutations) > 0

    for host_info, mutation in shard_mutations.items():
        assert host_info.shard_num is not None

        # wait for mutations to complete on shard
        cluster.map_all_hosts_in_shard(host_info.shard_num, mutation.wait).result()

        # check to make sure all mutations are marked as done
        assert all(cluster.map_all_hosts_in_shard(host_info.shard_num, mutation.is_done).result().values())


def test_alter_mutation_single_command(cluster: ClickhouseCluster) -> None:
    table = EVENTS_DATA_TABLE()
    count = 100

    # make sure there is some data to play with first
    cluster.map_one_host_per_shard(Query(f"INSERT INTO {table} SELECT * FROM generateRandom() LIMIT {count}")).result()

    # construct the runner
    sentinel_uuid = uuid.uuid1()  # unique to this test run to ensure we have a clean slate
    runner = AlterTableMutationRunner(
        table=table,
        commands={
            """
            UPDATE person_id = %(uuid)s, properties = %(properties)s
            -- this is a comment that will not appear in system.mutations
            WHERE 1 = /* this will also be stripped out during formatting */ 01
            """
        },
        parameters={"uuid": sentinel_uuid, "properties": json.dumps({"uuid": sentinel_uuid.hex})},
    )

    # nothing should be running yet
    existing_mutations = cluster.map_all_hosts(runner.find_existing_mutations).result()
    assert all(not mutations for mutations in existing_mutations.values())

    # start all mutations
    shard_mutations = cluster.map_one_host_per_shard(runner).result()
    wait_and_check_mutations_on_shards(cluster, shard_mutations)

    # check to ensure data is as expected to be after update
    for host_info in shard_mutations.keys():
        assert host_info.shard_num is not None
        query_results = cluster.map_all_hosts_in_shard(
            host_info.shard_num, Query(f"SELECT person_id, count() FROM {table} GROUP BY ALL ORDER BY ALL")
        ).result()
        assert all(result == [(sentinel_uuid, count)] for result in query_results.values())

    # submitting a duplicate mutation should just return the original and not schedule anything new
    get_mutations_count_query = Query("SELECT count() FROM system.mutations")
    mutations_count_before = cluster.map_all_hosts(get_mutations_count_query).result()

    duplicate_mutations = cluster.map_one_host_per_shard(runner).result()
    assert shard_mutations == duplicate_mutations

    assert cluster.map_all_hosts(get_mutations_count_query).result() == mutations_count_before

    with pytest.raises(MutationNotFound):
        assert cluster.any_host(MutationWaiter("x", {"y"}).is_done).result()


def test_alter_mutation_multiple_commands(cluster: ClickhouseCluster) -> None:
    table = EVENTS_DATA_TABLE()
    count = 100

    # make sure there is some data to play with first
    cluster.map_one_host_per_shard(Query(f"INSERT INTO {table} SELECT * FROM generateRandom() LIMIT {count}")).result()

    sentinel_uuid = uuid.uuid1()  # unique to this test run to ensure we have a clean slate

    with (
        materialized("events", f"{sentinel_uuid}_a") as column_a,
        materialized("events", f"{sentinel_uuid}_b") as column_b,
        materialized("events", f"{sentinel_uuid}_c") as column_c,
    ):
        runner = AlterTableMutationRunner(
            table=table,
            commands={f"MATERIALIZE COLUMN {column_a.name}", f"MATERIALIZE COLUMN {column_b.name}"},
        )

        # nothing should be running yet
        existing_mutations = cluster.map_all_hosts(runner.find_existing_mutations).result()
        assert all(not mutations for mutations in existing_mutations.values())

        # start all mutations
        shard_mutations = cluster.map_one_host_per_shard(runner).result()
        wait_and_check_mutations_on_shards(cluster, shard_mutations)

        # all commands should have an associated mutation id at this point
        existing_mutations = cluster.map_all_hosts(runner.find_existing_mutations).result()
        assert all(mutations.keys() == runner.commands for mutations in existing_mutations.values())

        # if we run the same mutation with a subset of commands, nothing new should be scheduled (this ensures after a
        # code change that removes a command from the mutation, we won't error when we mutations from previous versions)
        runner_with_single_command = AlterTableMutationRunner(
            table=table,
            commands={f"MATERIALIZE COLUMN {column_a.name}"},
        )

        # "start" all mutations (in actuality, this is a noop)
        shard_mutations = cluster.map_one_host_per_shard(runner_with_single_command).result()
        wait_and_check_mutations_on_shards(cluster, shard_mutations)

        # the command should still be the same from the previous run
        assert all(
            mutations == {command: existing_mutations[host][command] for command in runner_with_single_command.commands}
            for host, mutations in (
                cluster.map_all_hosts(runner_with_single_command.find_existing_mutations).result().items()
            )
        )

        # if we run the same mutation with additional commands, only the new command should be executed
        new_command = f"MATERIALIZE COLUMN {column_c.name}"
        runner_with_extra_command = AlterTableMutationRunner(
            table=table,
            commands={*runner.commands, new_command},
        )

        # the new command should not yet be findable
        assert cluster.map_all_hosts(runner_with_extra_command.find_existing_mutations).result() == existing_mutations

        # start all mutations
        shard_mutations = cluster.map_one_host_per_shard(runner_with_extra_command).result()
        wait_and_check_mutations_on_shards(cluster, shard_mutations)

        # now all commands should be present
        assert all(
            mutations.keys() == runner_with_extra_command.commands
            for mutations in (
                cluster.map_all_hosts(runner_with_extra_command.find_existing_mutations).result().values()
            )
        )


def test_map_hosts_by_role() -> None:
    bootstrap_client_mock = Mock()
    bootstrap_client_mock.execute = Mock()
    bootstrap_client_mock.execute.return_value = [
        ("host1", "9000", "1", "1", "online", "data"),
        ("host2", "9000", "1", "2", "online", "data"),
        ("host3", "9000", "1", "3", "offline", "data"),
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
        times_called.clear()

        cluster.map_hosts_by_role(lambda _: (), node_role=NodeRole.ALL, workload=Workload.OFFLINE).result()
        assert times_called[NodeRole.DATA] == 1
        assert times_called[NodeRole.COORDINATOR] == 0
        times_called.clear()

        cluster.map_hosts_by_role(lambda _: (), node_role=NodeRole.DATA, workload=Workload.ONLINE).result()
        assert times_called[NodeRole.DATA] == 2
        assert times_called[NodeRole.COORDINATOR] == 0
        times_called.clear()


def test_lightweight_delete(cluster: ClickhouseCluster) -> None:
    table = EVENTS_DATA_TABLE()
    count = 100

    cluster.map_one_host_per_shard(Query(f"TRUNCATE TABLE {table}")).result()

    # make sure there is some data to play with first
    cluster.map_one_host_per_shard(Query(f"INSERT INTO {table} SELECT * FROM generateRandom() LIMIT {count}")).result()

    [[[eid]]] = cluster.map_all_hosts(Query(f"SELECT uuid FROM {table} ORDER BY rand() LIMIT 1")).result().values()

    # construct the runner with a DELETE command
    runner = LightweightDeleteMutationRunner(
        table=table,
        predicate=f"uuid = %(uuid)s",
        parameters={"uuid": eid},
    )

    # start all mutations
    shard_mutations = cluster.map_one_host_per_shard(runner).result()
    wait_and_check_mutations_on_shards(cluster, shard_mutations)

    # check to ensure data is as expected to be after update (fewer rows visible than initially created)
    for host_info in shard_mutations.keys():
        assert host_info.shard_num is not None
        query_results = cluster.map_all_hosts_in_shard(
            host_info.shard_num, Query(f"SELECT count(1) FROM {table}")
        ).result()
        assert all(result[0][0] < count for result in query_results.values())


def test_alter_mutation_force_parameter(cluster: ClickhouseCluster) -> None:
    """Test that force=True skips checking for existing mutations"""
    table = EVENTS_DATA_TABLE()
    count = 100

    # Insert test data
    cluster.map_one_host_per_shard(Query(f"INSERT INTO {table} SELECT * FROM generateRandom() LIMIT {count}")).result()

    sentinel_uuid = uuid.uuid1()

    # First run a mutation normally
    runner = AlterTableMutationRunner(
        table=table,
        commands={"UPDATE person_id = %(uuid)s WHERE 1 = 1"},
        parameters={"uuid": sentinel_uuid},
    )

    # Run the mutation and wait for completion
    shard_mutations = cluster.map_one_host_per_shard(runner).result()
    wait_and_check_mutations_on_shards(cluster, shard_mutations)

    # Count mutations before force
    get_mutations_count = Query(
        "SELECT count() FROM system.mutations WHERE database = currentDatabase() AND table = %(table)s",
        {"table": table},
    )
    mutations_count_before = cluster.map_all_hosts(get_mutations_count).result()

    # Now run the same mutation with force=True
    runner_force = AlterTableMutationRunner(
        table=table,
        commands={"UPDATE person_id = %(uuid)s WHERE 1 = 1"},
        parameters={"uuid": sentinel_uuid},
        force=True,
    )

    # This should create a new mutation even though one already exists
    cluster.map_one_host_per_shard(runner_force).result()

    # Count mutations after force
    mutations_count_after = cluster.map_all_hosts(get_mutations_count).result()

    # Should have more mutations after using force=True
    for host in mutations_count_before:
        assert mutations_count_after[host][0][0] > mutations_count_before[host][0][0]
