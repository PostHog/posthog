from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import CoinGeckoSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CoinGeckoSource(SimpleSource[CoinGeckoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COINGECKO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.COIN_GECKO,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="CoinGecko",
            iconPath="/static/services/coingecko.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
