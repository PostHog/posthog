from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import EZOfficeInventorySourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EZOfficeInventorySource(SimpleSource[EZOfficeInventorySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EZOFFICEINVENTORY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EZ_OFFICE_INVENTORY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="EZOfficeInventory",
            iconPath="/static/services/ezofficeinventory.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
