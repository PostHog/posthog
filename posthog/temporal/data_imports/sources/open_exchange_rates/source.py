from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import OpenExchangeRatesSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OpenExchangeRatesSource(SimpleSource[OpenExchangeRatesSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENEXCHANGERATES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPEN_EXCHANGE_RATES,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Open Exchange Rates",
            iconPath="/static/services/open_exchange_rates.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
