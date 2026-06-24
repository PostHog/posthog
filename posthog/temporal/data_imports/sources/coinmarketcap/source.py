from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import CoinMarketCapSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CoinMarketCapSource(SimpleSource[CoinMarketCapSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COINMARKETCAP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.COIN_MARKET_CAP,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="CoinMarketCap",
            iconPath="/static/services/coinmarketcap.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
