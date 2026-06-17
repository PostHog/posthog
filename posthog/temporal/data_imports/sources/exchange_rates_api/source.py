from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import ExchangeRatesApiSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ExchangeRatesApiSource(SimpleSource[ExchangeRatesApiSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EXCHANGERATESAPI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EXCHANGE_RATES_API,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Exchange Rates API",
            iconPath="/static/services/exchange_rates_api.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
