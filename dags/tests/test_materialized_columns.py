import pydantic
import pytest

from dags.materialized_columns import PartitionRange


def test_partition_range():
    assert set(PartitionRange(lower="202401", upper="202403")) == {"202401", "202402", "202403"}

    assert set(PartitionRange(lower="202403", upper="202401")) == set()

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="2024XX", upper="202403")

    with pytest.raises(pydantic.ValidationError):
        PartitionRange(lower="202401", upper="2024XX")
