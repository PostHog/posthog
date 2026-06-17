from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import TwelveDataSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TwelveDataSource(SimpleSource[TwelveDataSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TWELVEDATA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TWELVE_DATA,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Twelve Data",
            iconPath="/static/services/twelve_data.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
