import collections.abc

import pytest
from unittest.mock import patch

import pyarrow as pa
from structlog.testing import capture_logs

from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.service import AnyBatchExportModel, BatchExportHogQLModel, BatchExportPersonsModel
from products.batch_exports.backend.temporal.destinations import (
    bigquery_batch_export,
    databricks_batch_export,
    postgres_batch_export,
    redshift_batch_export,
    snowflake_batch_export,
)
from products.batch_exports.backend.temporal.errors import ColumnTypeMappingError, UnsupportedColumnTypeError
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.utils import handle_column_type_mapping_errors, handle_non_retryable_errors


def _map_bigquery(model: AnyBatchExportModel, schema: pa.Schema) -> object:
    with handle_column_type_mapping_errors(model):
        return bigquery_batch_export.BigQueryTable.from_arrow_schema(
            schema, table_id="t", dataset_id="s", project_id="p", primary_key=(), version_key=()
        )


def _map_snowflake(model: AnyBatchExportModel, schema: pa.Schema) -> object:
    with handle_column_type_mapping_errors(model):
        return snowflake_batch_export.SnowflakeTable.from_arrow_schema(
            schema, name="t", table_schema="s", database="d", primary_key=(), version_key=()
        )


def _map_redshift(model: AnyBatchExportModel, schema: pa.Schema) -> object:
    return redshift_batch_export._get_table_schemas(model, schema, properties_data_type="varchar")


def _map_postgres(model: AnyBatchExportModel, schema: pa.Schema) -> object:
    return postgres_batch_export._get_table_fields(model, schema)


def _map_databricks(model: AnyBatchExportModel, schema: pa.Schema) -> object:
    return databricks_batch_export._get_databricks_table_settings(model, schema, use_variant_type=False)


SCHEMA_MAPPERS: list[
    tuple[str, collections.abc.Callable[[AnyBatchExportModel, pa.Schema], object], collections.abc.Sequence[str]]
] = [
    ("BigQuery", _map_bigquery, bigquery_batch_export.NON_RETRYABLE_ERROR_TYPES),
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
    "model, expected_error",
    [
        (BatchExportHogQLModel(query="SELECT 1", user_id=1, modifiers={}), UnsupportedColumnTypeError),
        (BatchExportPersonsModel(), ColumnTypeMappingError),
    ],
    ids=["hogql", "persons"],
)
@pytest.mark.parametrize(
    "column_type",
    [pa.decimal256(76, 9), pa.map_(pa.string(), pa.string()), pa.struct([("a", pa.int64())]), pa.null()],
    ids=str,
)
async def test_schema_mapping_logs_and_retries_an_unsupported_column_type(
    destination: str,
    mapper: collections.abc.Callable[[AnyBatchExportModel, pa.Schema], object],
    non_retryable_error_types: collections.abc.Sequence[str],
    model: AnyBatchExportModel,
    expected_error: type[Exception],
    column_type: pa.DataType,
) -> None:
    schema = pa.schema([pa.field("amount", column_type, nullable=True)])

    @handle_non_retryable_errors(non_retryable_error_types)
    async def map_schema() -> BatchExportResult:
        mapper(model, schema)
        return BatchExportResult()

    with (
        patch("products.batch_exports.backend.temporal.utils.LOGGER", get_write_only_logger(__name__)),
        capture_logs() as logs,
        pytest.raises(expected_error) as exc_info,
    ):
        await map_schema()

    assert "amount" in str(exc_info.value)
    assert destination in str(exc_info.value)
    assert str(column_type) in str(exc_info.value)
    if expected_error is UnsupportedColumnTypeError:
        assert isinstance(exc_info.value.__cause__, ColumnTypeMappingError)
    warnings = [log for log in logs if log["log_level"] == "warning"]
    assert warnings == [
        {
            "event": "Unsupported column type in batch export",
            "log_level": "warning",
            "destination": destination,
            "column": "amount",
            "column_type": str(column_type),
            "error_type": expected_error.__name__,
            "retryable": True,
        }
    ]


@pytest.mark.asyncio
async def test_unsupported_column_warning_reflects_non_retryable_classification() -> None:
    error = UnsupportedColumnTypeError("PostgreSQL", "amount", pa.null())

    @handle_non_retryable_errors(("UnsupportedColumnTypeError",))
    async def export() -> BatchExportResult:
        raise error

    with (
        patch("products.batch_exports.backend.temporal.utils.LOGGER", get_write_only_logger(__name__)),
        capture_logs() as logs,
    ):
        result = await export()

    assert result == BatchExportResult.from_exception(error)
    assert [log for log in logs if log["log_level"] == "warning"] == [
        {
            "event": "Unsupported column type in batch export",
            "log_level": "warning",
            "destination": "PostgreSQL",
            "column": "amount",
            "column_type": "null",
            "error_type": "UnsupportedColumnTypeError",
            "retryable": False,
        }
    ]


def test_column_type_mapping_handler_preserves_unrelated_type_errors() -> None:
    model = BatchExportHogQLModel(query="SELECT 1", user_id=1, modifiers={})
    error = TypeError("Invalid mapper arguments")

    with pytest.raises(TypeError) as exc_info:
        with handle_column_type_mapping_errors(model):
            raise error

    assert exc_info.value is error
