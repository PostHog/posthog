from typing import Any

from unittest.mock import MagicMock

import pyarrow as pa
from parameterized import parameterized

from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline_v3.load.processor import _apply_partitioning, _get_write_type
from posthog.temporal.data_imports.pipelines.test_mocks import mock_delta_table


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


_COL_ID = pa.field("id", pa.int64())
_COL_PARTITION = pa.field(PARTITION_KEY, pa.string())


class TestApplyPartitioning:
    """Regression coverage for the `DeltaError: Specified table partitioning does not match` bug.

    When a delta table contains `_ph_partition_key` in its schema but NOT in its
    partition columns (e.g. left over from a prior write committed with
    `partition_by=None`), the v3 loader must skip partitioning subsequent writes
    to avoid delta-rs rejecting the `partition_by=PARTITION_KEY` argument.
    """

    @parameterized.expand(
        [
            # Column in schema but NOT in partition_columns → skip (the exact bug scenario).
            ("column_in_schema_not_partitioned", [_COL_ID, _COL_PARTITION], [], False),
            # `metadata().partition_columns` returning None → skip defensively.
            ("partition_columns_is_none", [_COL_ID, _COL_PARTITION], None, False),
            # Truly partitioned by `_ph_partition_key` → happy path, partitioning applies.
            ("table_partitioned_by_key", [_COL_ID, _COL_PARTITION], [PARTITION_KEY], True),
        ]
    )
    def test_respects_existing_delta_partition_columns(
        self,
        _case: str,
        schema_fields: list[pa.Field],
        partition_columns: list[str] | None,
        expect_key: bool,
    ):
        pa_table = pa.table({"id": [1, 2, 3]})
        delta_table = mock_delta_table(schema_fields=schema_fields, partition_columns=partition_columns)

        schema_kwargs: dict[str, Any] = {}
        export_kwargs: dict[str, Any] = {"partition_keys": ["id"]}
        if expect_key:
            schema_kwargs.update(
                partitioning_enabled=True,
                partition_mode="md5",
                partitioning_keys=["id"],
            )
            export_kwargs["partition_count"] = 10

        result = _apply_partitioning(
            export_signal=_export_signal(**export_kwargs),
            pa_table=pa_table,
            existing_delta_table=delta_table,
            schema=_schema(**schema_kwargs),
        )

        if expect_key:
            assert PARTITION_KEY in result.column_names
        else:
            assert PARTITION_KEY not in result.column_names
            assert result.equals(pa_table)

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
