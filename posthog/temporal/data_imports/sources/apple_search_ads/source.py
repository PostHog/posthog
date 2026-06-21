from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import AppleSearchAdsSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AppleSearchAdsSource(SimpleSource[AppleSearchAdsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPLESEARCHADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.APPLE_SEARCH_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Apple Search Ads",
            iconPath="/static/services/apple_search_ads.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
