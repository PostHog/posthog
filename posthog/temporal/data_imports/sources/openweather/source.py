from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import OpenWeatherSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OpenWeatherSource(SimpleSource[OpenWeatherSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENWEATHER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPEN_WEATHER,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="OpenWeather",
            iconPath="/static/services/openweather.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
