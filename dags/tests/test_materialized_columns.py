import time
import contextlib
from collections.abc import Iterator, Mapping
from datetime import datetime
from uuid import UUID

import pytest
from posthog.test.base import materialized

import dagster
import pydantic
from clickhouse_driver import Client

from posthog.clickhouse.cluster import ClickhouseCluster, Query

from dags.materialized_columns import (
    MaterializationConfig,
    PartitionRange,
    join_mappings,
    materialize_column,
    run_materialize_mutations,
)


def test_join_mappings():
    assert join_mappings({}) == {}

    assert join_mappings({1: {"a": 1}}) == {"a": {1: 1}}

    # overlapping keys
    assert join_mappings({1: {"a": 1}, 2: {"a": 2}}) == {"a": {1: 1, 2: 2}}

    # non-overlapping keys
    assert join_mappings({1: {"a": 1}, 2: {"b": 2}}) == {"a": {1: 1}, "b": {2: 2}}


def test_partition_range_validation():
    assert set(PartitionRange(lower="202401", upper="202403").iter_ids()) == {"202401", "202402", "202403"}

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="202403", upper="202401")  # lower > upper

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="", upper="202403")

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="202401", upper="")


def test_materialization_config_force_default():
    # Test that force defaults to False
    config = MaterializationConfig(
        table="test_table",
        columns=["test_column"],
        indexes=[],
        partitions=PartitionRange(lower="202401", upper="202403"),
    )
    assert config.force is False


@contextlib.contextmanager
def override_mergetree_settings(cluster: ClickhouseCluster, table: str, settings: Mapping[str, str]) -> Iterator[None]:
    def alter_table_add_settings(client: Client) -> None:
        client.execute(f"ALTER TABLE {table} MODIFY SETTING " + ", ".join(" = ".join(i) for i in settings.items()))

    def alter_table_reset_settings(client) -> None:
        client.execute(f"ALTER TABLE {table} RESET SETTING " + ", ".join(settings.keys()))

    try:
        cluster.map_all_hosts(alter_table_add_settings).result()
        yield
    finally:
        cluster.map_all_hosts(alter_table_reset_settings).result()


def test_sharded_table_job(cluster: ClickhouseCluster):
    partitions = PartitionRange(lower="202401", upper="202403")

    def populate_test_data(client: Client) -> None:
        for date in partitions.iter_dates():
            dt = datetime(date.year, date.month, date.day)
            client.execute(
                "INSERT INTO writable_events (timestamp, uuid) VALUES",
                [(dt, UUID(int=i)) for i in range(100)],
            )

    with override_mergetree_settings(
        cluster,
        "sharded_events",
        {"min_bytes_for_wide_part": "1", "min_rows_for_wide_part": "1"},
    ):
        cluster.any_host(populate_test_data).result()

        # stop merges on all hosts so that we don't inadvertently write data for the materialized column due to merges
        cluster.map_all_hosts(Query("SYSTEM STOP MERGES")).result()

        # try our best to make sure that merges resume after this test, even if we throw in the test block below
        resume_merges = lambda: cluster.map_all_hosts(Query("SYSTEM START MERGES")).result()
        exit_handlers = contextlib.ExitStack()
        exit_handlers.callback(resume_merges)

        with exit_handlers, materialized("events", f"$test_{time.time()}", create_minmax_index=True) as column:
            materialize_column_config = MaterializationConfig(
                table="sharded_events",
                columns=[column.name],
                indexes=[],
                partitions=partitions,
            )

            # before running the job, the materialized column should not have been written to any parts
            remaining_partitions_by_shard = cluster.map_one_host_per_shard(
                materialize_column_config.get_mutations_to_run
            ).result()
            for _shard_host, shard_mutations in remaining_partitions_by_shard.items():
                assert len(shard_mutations) == 3
                for mutation in shard_mutations.values():
                    # mutations should only be for the column
                    assert all("MATERIALIZE COLUMN" in command for command in mutation.commands)

            # merges need to be resumed to allow the mutations to move forward (there is a bit of a race condition here:
            # if the table is preemptively merged prior to running the job, we're actually testing the deduplication
            # behavior, not the mutation itself. this isn't intended but is probably okay to do)
            resume_merges()

            materialize_column.execute_in_process(
                run_config=dagster.RunConfig(
                    {run_materialize_mutations.name: {"config": materialize_column_config.model_dump()}},
                ),
                resources={"cluster": cluster},
            )

            # after running the job, the materialized column should have been written to all parts
            remaining_partitions_by_shard = cluster.map_one_host_per_shard(
                materialize_column_config.get_mutations_to_run
            ).result()
            for _shard_host, shard_mutations in remaining_partitions_by_shard.items():
                assert shard_mutations == {}

            # XXX: if ee.* not importable, this text should have been xfailed by the materialize context manager
            from ee.clickhouse.materialized_columns.columns import get_minmax_index_name

            materialize_column_and_index_config = MaterializationConfig(
                table="sharded_events",
                columns=[column.name],
                indexes=[get_minmax_index_name(column.name)],
                partitions=partitions,
            )

            remaining_partitions_by_shard = cluster.map_one_host_per_shard(
                materialize_column_and_index_config.get_mutations_to_run
            ).result()
            for _shard_host, shard_mutations in remaining_partitions_by_shard.items():
                assert len(shard_mutations) == 3
                for mutation in shard_mutations.values():
                    # skip the column (as it has been materialized), but materialize the index
                    assert all("MATERIALIZE INDEX" in command for command in mutation.commands)

            materialize_column.execute_in_process(
                run_config=dagster.RunConfig(
                    {run_materialize_mutations.name: {"config": materialize_column_and_index_config.model_dump()}},
                ),
                resources={"cluster": cluster},
            )

            # XXX: ideally we'd assert here that the index now exists, but there is no way to do that like there is for columns

            # Test force option: even though columns are already materialized, force should re-materialize them
            force_materialize_config = MaterializationConfig(
                table="sharded_events",
                columns=[column.name],
                indexes=[],
                partitions=partitions,
                force=True,
            )

            # When force=True, should return mutations for all partitions even though they're already materialized
            remaining_partitions_by_shard = cluster.map_one_host_per_shard(
                force_materialize_config.get_mutations_to_run
            ).result()
            for _shard_host, shard_mutations in remaining_partitions_by_shard.items():
                assert len(shard_mutations) == 3
                for mutation in shard_mutations.values():
                    # mutations should only be for the column
                    assert all("MATERIALIZE COLUMN" in command for command in mutation.commands)
