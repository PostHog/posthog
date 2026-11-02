import collections.abc

import pytest
from unittest.mock import patch

import pyarrow as pa
from structlog.testing import capture_logs

from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.temporal.destinations import (
    databricks_batch_export,
    postgres_batch_export,
    redshift_batch_export,
    snowflake_batch_export,
)
from products.batch_exports.backend.temporal.errors import UnsupportedColumnTypeError
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.utils import handle_non_retryable_errors


def _map_snowflake(schema: pa.Schema) -> object:
    return snowflake_batch_export.SnowflakeTable.from_arrow_schema(
        schema, name="t", table_schema="s", database="d", primary_key=(), version_key=()
    )


def _map_redshift(schema: pa.Schema) -> object:
    return redshift_batch_export.get_redshift_fields_from_record_schema(schema, known_super_columns=[], use_super=False)


def _map_postgres(schema: pa.Schema) -> object:
    return postgres_batch_export.get_postgres_fields_from_record_schema(schema, known_json_columns=[])


def _map_databricks(schema: pa.Schema) -> object:
    return databricks_batch_export._get_databricks_fields_from_record_schema(schema, known_variant_columns=[])


SCHEMA_MAPPERS: list[tuple[str, collections.abc.Callable[[pa.Schema], object], collections.abc.Sequence[str]]] = [
    ("Snowflake", _map_snowflake, snowflake_batch_export.NON_RETRYABLE_ERROR_TYPES),
    ("Redshift", _map_redshift, redshift_batch_export.NON_RETRYABLE_ERROR_TYPES),
    ("PostgreSQL", _map_postgres, postgres_batch_export.NON_RETRYABLE_ERROR_TYPES),
    ("Databricks", _map_databricks, databricks_batch_export.NON_RETRYABLE_ERROR_TYPES),
]


@pytest.mark.parametrize(
    "destination, mapper, non_retryable_error_types", SCHEMA_MAPPERS, ids=[m[0] for m in SCHEMA_MAPPERS]
)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "column_type",
    [pa.decimal256(76, 9), pa.map_(pa.string(), pa.string()), pa.struct([("a", pa.int64())]), pa.null()],
    ids=str,
)
async def test_schema_mapping_logs_and_retries_an_unsupported_column_type(
    destination: str,
    mapper: collections.abc.Callable[[pa.Schema], object],
    non_retryable_error_types: collections.abc.Sequence[str],
    column_type: pa.DataType,
) -> None:
    schema = pa.schema([pa.field("amount", column_type, nullable=True)])

    @handle_non_retryable_errors(non_retryable_error_types)
    async def map_schema() -> BatchExportResult:
        mapper(schema)
        return BatchExportResult()

    with (
        patch("products.batch_exports.backend.temporal.utils.LOGGER", get_write_only_logger(__name__)),
        capture_logs() as logs,
        pytest.raises(UnsupportedColumnTypeError) as exc_info,
    ):
        await map_schema()

    assert "amount" in str(exc_info.value)
    assert destination in str(exc_info.value)
    assert str(column_type) in str(exc_info.value)
    warnings = [log for log in logs if log["log_level"] == "warning"]
    assert warnings == [
        {
            "event": "Unsupported column type in batch export",
            "log_level": "warning",
            "destination": destination,
            "column": "amount",
            "column_type": str(column_type),
        }
    ]
