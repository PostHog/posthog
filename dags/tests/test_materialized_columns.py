import dagster
import pydantic
import pytest

from dags.materialized_columns import (
    PartitionRange,
    materialize_column,
    run_materialize_mutations,
)
from posthog.clickhouse.cluster import ClickhouseCluster


def test_partition_range():
    assert set(PartitionRange(lower="202401", upper="202403")) == {"202401", "202402", "202403"}

    assert set(PartitionRange(lower="202403", upper="202401")) == set()

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="2024XX", upper="202403")

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="202401", upper="2024XX")


def test_job(cluster: ClickhouseCluster):
    materialize_column.execute_in_process(
        run_config=dagster.RunConfig(
            {
                run_materialize_mutations.name: {
                    "config": {
                        "table": "sharded_events",
                        "column": "mat_$ip",
                        "partitions": {"upper": "202401", "lower": "202412"},
                    }
                }
            }
        ),
        resources={"cluster": cluster},
    )
