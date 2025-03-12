import contextlib
import time
from collections.abc import Iterator, Mapping
from datetime import datetime
from uuid import UUID

import dagster
import pydantic
import pytest
from clickhouse_driver import Client

from dags.materialized_columns import (
    MaterializeColumnConfig,
    PartitionRange,
    materialize_column,
    run_materialize_mutations,
)
from posthog.clickhouse.cluster import ClickhouseCluster, Query
from posthog.test.base import materialized


def test_partition_range_validation():
    assert set(PartitionRange(lower="202401", upper="202403").iter_ids()) == {"202401", "202402", "202403"}

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="202403", upper="202401")  # lower > upper

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="", upper="202403")

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="202401", upper="")


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

        with exit_handlers, materialized("events", f"$test_{time.time()}") as column:
            config = MaterializeColumnConfig(
                table="sharded_events",
                column=column.name,
                partitions=partitions,
            )

            # before running the job, the materialized column should not have been written to any parts
            # TODO: fix
            # remaining_partitions_by_shard = cluster.map_one_host_per_shard(config.get_remaining_partitions).result()
            # for _shard_host, shard_partitions_remaining in remaining_partitions_by_shard.items():
            #     assert shard_partitions_remaining == set(config.partitions.iter_ids())

            # merges need to be resumed to allow the mutations to move forward (there is a bit of a race condition here:
            # if the table is preemptively merged prior to running the job, we're actually testing the deduplication
            # behavior, not the mutation itself. this isn't intended but is probably okay to do)
            resume_merges()

            materialize_column.execute_in_process(
                run_config=dagster.RunConfig(
                    {run_materialize_mutations.name: {"config": config.model_dump()}},
                ),
                resources={"cluster": cluster},
            )

            # after running the job, the materialized column should have been written to all parts
            # TODO: fix
            # remaining_partitions_by_shard = cluster.map_one_host_per_shard(config.get_remaining_partitions).result()
            # for _shard_host, shard_partitions_remaining in remaining_partitions_by_shard.items():
            #     assert shard_partitions_remaining == set()
