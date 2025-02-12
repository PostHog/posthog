import contextlib
from collections.abc import Iterator, Mapping
from datetime import datetime
import time
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
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.hogql.test.test_printer import materialized  # bad idea


def test_partition_range_validation():
    assert set(PartitionRange(lower="202401", upper="202403").iter_ids()) == {"202401", "202402", "202403"}

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="202403", upper="202401")  # lower > upper

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="", upper="202403")

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="202401", upper="")


@contextlib.contextmanager
def stop_merges(cluster: ClickhouseCluster, table: str):
    try:
        cluster.map_all_hosts(lambda c: c.execute(f"SYSTEM STOP MERGES {table}")).result()
        yield
    finally:
        cluster.map_all_hosts(lambda c: c.execute(f"SYSTEM START MERGES {table}")).result()


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
    partitions = PartitionRange(lower="202401", upper="202402")

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

        with materialized("events", f"$xyz_{time.time()}") as column:
            config = MaterializeColumnConfig(
                table="sharded_events",
                column=column.name,
                partitions=partitions,
            )

            remaining_partitions_by_shard = cluster.map_one_host_per_shard(config.get_remaining_partitions).result()
            for _shard_host, shard_partitions_remaining in remaining_partitions_by_shard.items():
                assert shard_partitions_remaining == set(config.partitions.iter_ids())

            materialize_column.execute_in_process(
                run_config=dagster.RunConfig(
                    {run_materialize_mutations.name: {"config": config.model_dump()}},
                ),
                resources={"cluster": cluster},
            )

            remaining_partitions_by_shard = cluster.map_one_host_per_shard(config.get_remaining_partitions).result()
            for _shard_host, shard_partitions_remaining in remaining_partitions_by_shard.items():
                assert shard_partitions_remaining == set()
