from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa
import deltalake as deltalake
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.utils import pyarrow_schema_from_arrow_exportable
from posthog.temporal.data_imports.sources.revenuecat.constants import (
    EVENT_RESOURCE_NAME,
    REVENUECAT_WEBHOOK_DOUBLE_FIELDS,
)

from products.data_warehouse.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper


async def maybe_repair_revenuecat_event_double_columns(
    *,
    source_type: str | None,
    schema_name: str,
    incoming_table: pa.Table,
    delta_table: deltalake.DeltaTable | None,
    delta_table_helper: DeltaTableHelper,
    logger: FilteringBoundLogger,
) -> deltalake.DeltaTable | None:
    if source_type != ExternalDataSourceType.REVENUECAT or schema_name != EVENT_RESOURCE_NAME or delta_table is None:
        return delta_table

    delta_schema = pyarrow_schema_from_arrow_exportable(delta_table.schema())
    columns_to_widen: dict[str, pa.DataType] = {}
    for field_name in REVENUECAT_WEBHOOK_DOUBLE_FIELDS:
        if field_name not in delta_schema.names or field_name not in incoming_table.column_names:
            continue

        delta_field = delta_schema.field(field_name)
        incoming_field = incoming_table.field(field_name)
        if pa.types.is_integer(delta_field.type) and pa.types.is_floating(incoming_field.type):
            columns_to_widen[field_name] = pa.float64()

    if not columns_to_widen:
        return delta_table

    await logger.awarning(
        "repairing_revenuecat_event_double_columns",
        columns=list(columns_to_widen.keys()),
    )
    return await delta_table_helper.rewrite_columns(columns_to_widen)
