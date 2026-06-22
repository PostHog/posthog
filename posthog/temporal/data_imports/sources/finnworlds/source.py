from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import FinnworldsSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FinnworldsSource(SimpleSource[FinnworldsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FINNWORLDS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FINNWORLDS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Finnworlds",
            iconPath="/static/services/finnworlds.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
