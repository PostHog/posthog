from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import RepairshoprSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RepairshoprSource(SimpleSource[RepairshoprSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REPAIRSHOPR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.REPAIRSHOPR,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Repairshopr",
            iconPath="/static/services/repairshopr.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
