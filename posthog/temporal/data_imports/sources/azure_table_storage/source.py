from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import AzureTableStorageSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AzureTableStorageSource(SimpleSource[AzureTableStorageSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZURETABLESTORAGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AZURE_TABLE_STORAGE,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Azure Table Storage",
            iconPath="/static/services/azure_table_storage.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
