from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import VismaEconomicSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class VismaEconomicSource(SimpleSource[VismaEconomicSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VISMAECONOMIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.VISMA_ECONOMIC,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Visma Economic",
            iconPath="/static/services/visma_economic.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
