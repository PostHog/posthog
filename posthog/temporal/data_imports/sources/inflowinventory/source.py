from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import InflowinventorySourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class InflowinventorySource(SimpleSource[InflowinventorySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INFLOWINVENTORY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INFLOWINVENTORY,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Inflowinventory",
            iconPath="/static/services/inflowinventory.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
