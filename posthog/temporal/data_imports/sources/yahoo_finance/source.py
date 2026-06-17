from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import YahooFinanceSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class YahooFinanceSource(SimpleSource[YahooFinanceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YAHOOFINANCE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.YAHOO_FINANCE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Yahoo Finance",
            iconPath="/static/services/yahoo_finance.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
