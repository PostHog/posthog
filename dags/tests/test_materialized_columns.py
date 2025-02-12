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
    assert set(PartitionRange(lower="202401", upper="202403").iter()) == {"202401", "202402", "202403"}

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="202403", upper="202401")  # lower > upper

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="2024XX", upper="202403")

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="202401", upper="2024XX")


def test_sharded_table_job(cluster: ClickhouseCluster):
    # TODO: create new materialized column
    column = "mat_$ip"

    config = MaterializeColumnConfig(
        table="sharded_events",
        column=column,
        partitions=PartitionRange(lower="202401", upper="202412"),
    )

    # TODO: make sure all parts are wide
    remaining_partitions_by_shard = cluster.map_one_host_per_shard(config.get_remaining_partitions).result()
    for _shard_host, shard_partitions_remaining in remaining_partitions_by_shard.items():
        assert shard_partitions_remaining == set(config.partitions.iter())

    materialize_column.execute_in_process(
        run_config=dagster.RunConfig(
            {run_materialize_mutations.name: {"config": config.model_dump()}},
        ),
        resources={"cluster": cluster},
    )

    remaining_partitions_by_shard = cluster.map_one_host_per_shard(config.get_remaining_partitions).result()
    for _shard_host, shard_partitions_remaining in remaining_partitions_by_shard.items():
        assert shard_partitions_remaining == set()
