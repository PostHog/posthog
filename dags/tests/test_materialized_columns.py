from datetime import datetime
from uuid import UUID
from clickhouse_driver import Client
import dagster
import pydantic
import pytest

from dags.materialized_columns import (
    MaterializeColumnConfig,
    PartitionRange,
    materialize_column,
    run_materialize_mutations,
)
from posthog.clickhouse.cluster import ClickhouseCluster


def test_partition_range_validation():
    assert set(PartitionRange(lower="202401", upper="202403").iter_ids()) == {"202401", "202402", "202403"}

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="202403", upper="202401")  # lower > upper

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="2024XX", upper="202403")

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="202401", upper="2024XX")


def test_sharded_table_job(cluster: ClickhouseCluster):
    config = MaterializeColumnConfig(
        table="sharded_events",
        column="mat_$ip",  # TODO: create new materialized column
        partitions=PartitionRange(lower="202401", upper="202412"),
    )

    # make sure all parts are wide
    def setup_table_for_wide_part(client: Client) -> None:
        client.execute(
            f"ALTER TABLE {config.table} MODIFY SETTING min_bytes_for_wide_part = 1, min_rows_for_wide_part = 1",
        )

    cluster.map_all_hosts(setup_table_for_wide_part).result()

    def populate_test_data(client: Client) -> None:
        for date in config.partitions.iter_dates():
            dt = datetime(date.year, date.month, date.day)
            client.execute(
                "INSERT INTO writable_events (timestamp, uuid) VALUES",
                [(dt, UUID(int=i)) for i in range(100)],
            )

    cluster.any_host(populate_test_data).result()

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
