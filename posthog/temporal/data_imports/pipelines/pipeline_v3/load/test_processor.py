from typing import Any

from unittest.mock import MagicMock

import pyarrow as pa
from parameterized import parameterized

from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline_v3.load.processor import _apply_partitioning, _get_write_type


class TestGetWriteType:
    @parameterized.expand(
        [
            ("incremental", "incremental"),
            ("cdc", "incremental"),
            ("append", "append"),
            ("full_refresh", "full_refresh"),
        ]
    )
    def test_mapping(self, sync_type, expected):
        assert _get_write_type(sync_type) == expected


def _export_signal(**overrides: Any) -> MagicMock:
    signal = MagicMock()
    signal.partition_keys = overrides.get("partition_keys")
    signal.partition_count = overrides.get("partition_count")
    signal.partition_size = overrides.get("partition_size")
    signal.partition_mode = overrides.get("partition_mode")
    signal.partition_format = overrides.get("partition_format")
    return signal


def _schema(**overrides: Any) -> MagicMock:
    schema = MagicMock()
    schema.partitioning_enabled = overrides.get("partitioning_enabled", True)
    schema.partition_mode = overrides.get("partition_mode")
    schema.partition_format = overrides.get("partition_format")
    schema.partitioning_keys = overrides.get("partitioning_keys")
    schema.set_partitioning_enabled = MagicMock()
    return schema


def _delta_table(*, schema_fields: list[pa.Field], partition_columns: list[str]) -> MagicMock:
    arrow_schema = pa.schema(schema_fields)
    table = MagicMock()
    table.schema = MagicMock(return_value=MagicMock(to_arrow=MagicMock(return_value=arrow_schema)))
    table.metadata = MagicMock(return_value=MagicMock(partition_columns=list(partition_columns)))
    return table


class TestApplyPartitioningExistingUnpartitionedTable:
    """Regression tests for the `DeltaError: Specified table partitioning does not match` bug.

    When a delta table contains `_ph_partition_key` in its schema but NOT in its
    partition columns (e.g. left over from a prior write committed with
    `partition_by=None`), the v3 loader must skip partitioning subsequent writes
    to avoid delta-rs rejecting the `partition_by=PARTITION_KEY` argument.
    """

    def test_skips_partitioning_when_column_in_schema_but_not_in_partition_columns(self):
        pa_table = pa.table({"id": [1, 2, 3]})

        delta_table = _delta_table(
            schema_fields=[
                pa.field("id", pa.int64()),
                pa.field(PARTITION_KEY, pa.string()),  # column exists in schema
            ],
            partition_columns=[],  # but table is NOT actually partitioned
        )

        result = _apply_partitioning(
            export_signal=_export_signal(partition_keys=["id"]),
            pa_table=pa_table,
            existing_delta_table=delta_table,
            schema=_schema(),
        )

        assert PARTITION_KEY not in result.column_names
        assert result.equals(pa_table)

    def test_skips_partitioning_when_partition_columns_is_none(self):
        """Defensive: `metadata().partition_columns` could be None on some delta-rs versions."""
        pa_table = pa.table({"id": [1, 2, 3]})

        delta_table = MagicMock()
        delta_table.schema = MagicMock(
            return_value=MagicMock(
                to_arrow=MagicMock(
                    return_value=pa.schema([pa.field("id", pa.int64()), pa.field(PARTITION_KEY, pa.string())])
                )
            )
        )
        delta_table.metadata = MagicMock(return_value=MagicMock(partition_columns=None))

        result = _apply_partitioning(
            export_signal=_export_signal(partition_keys=["id"]),
            pa_table=pa_table,
            existing_delta_table=delta_table,
            schema=_schema(),
        )

        assert PARTITION_KEY not in result.column_names

    def test_applies_partitioning_when_table_is_partitioned_by_key(self):
        pa_table = pa.table({"id": [1, 2, 3]})

        delta_table = _delta_table(
            schema_fields=[
                pa.field("id", pa.int64()),
                pa.field(PARTITION_KEY, pa.string()),
            ],
            partition_columns=[PARTITION_KEY],
        )

        schema = _schema(
            partitioning_enabled=True,
            partition_mode="md5",
            partitioning_keys=["id"],
        )

        result = _apply_partitioning(
            export_signal=_export_signal(partition_keys=["id"], partition_count=10),
            pa_table=pa_table,
            existing_delta_table=delta_table,
            schema=schema,
        )

        assert PARTITION_KEY in result.column_names

    def test_skips_partitioning_when_no_partition_keys(self):
        pa_table = pa.table({"id": [1, 2, 3]})

        result = _apply_partitioning(
            export_signal=_export_signal(partition_keys=None),
            pa_table=pa_table,
            existing_delta_table=None,
            schema=_schema(),
        )

        assert PARTITION_KEY not in result.column_names
        assert result.equals(pa_table)
