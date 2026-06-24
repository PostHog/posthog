from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import ZohoBooksSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZohoBooksSource(SimpleSource[ZohoBooksSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOHOBOOKS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZOHO_BOOKS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Zoho Books",
            iconPath="/static/services/zoho_books.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
