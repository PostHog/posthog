import json
from typing import Any, Literal

from django.db.models import F

import pyarrow as pa
import pyarrow.compute as pc
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.utils import normalize_column_name

from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema, process_incremental_value
from products.data_warehouse.backend.types import ExternalDataSourceType


def update_job_row_count(job_id: str, count: int, logger: FilteringBoundLogger) -> None:
    logger.debug(f"Updating rows_synced with +{count}")
    ExternalDataJob.objects.filter(id=job_id).update(rows_synced=F("rows_synced") + count)


def _extract_nested_value(row_value: Any, nested_keys: list[str]) -> Any:
    """Extract a value from a nested path within a JSON string or dict."""
    if row_value is None:
        return None

    # If it's a string, try to parse as JSON
    if isinstance(row_value, str):
        try:
            row_value = json.loads(row_value)
        except (json.JSONDecodeError, TypeError):
            return None

    # Traverse the nested path
    for key in nested_keys:
        if isinstance(row_value, dict):
            row_value = row_value.get(key)
        else:
            return None

    return row_value


def get_incremental_field_value(
    schema: ExternalDataSchema | None, table: pa.Table, aggregate: Literal["max"] | Literal["min"] = "max"
) -> Any:
    if schema is None or schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH:
        return None

    incremental_field_name: str | list[str] | None = schema.sync_type_config.get("incremental_field")
    if incremental_field_name is None:
        return None

    # Check if this is a nested path as an array (e.g., ["attributes", "updated_at"])
    if isinstance(incremental_field_name, list):
        column_name = normalize_column_name(incremental_field_name[0])
        nested_keys = incremental_field_name[1:]

        column = table[column_name]
        values = [_extract_nested_value(val, nested_keys) for val in column.to_pylist()]
    else:
        column = table[normalize_column_name(incremental_field_name)]
        values = column.to_pylist()

    processed_column = pa.array([process_incremental_value(val, schema.incremental_field_type) for val in values])

    if aggregate == "max":
        last_value = pc.max(processed_column)
    elif aggregate == "min":
        last_value = pc.min(processed_column)
    else:
        raise Exception(f"Unsupported aggregate function for get_incremental_field_value: {aggregate}")

    return last_value.as_py()


def supports_partial_data_loading(schema: ExternalDataSchema) -> bool:
    """
    We should be able to roll this out to all source types in the future.
    Currently only Stripe sources support partial data loading.
    """
    return schema.source.source_type == ExternalDataSourceType.STRIPE
