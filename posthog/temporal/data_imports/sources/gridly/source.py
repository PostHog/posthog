from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import GridlySourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GridlySource(SimpleSource[GridlySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GRIDLY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GRIDLY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Gridly",
            iconPath="/static/services/gridly.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
