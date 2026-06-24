from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import AlpacaBrokerAPISourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AlpacaBrokerAPISource(SimpleSource[AlpacaBrokerAPISourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ALPACABROKERAPI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ALPACA_BROKER_API,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Alpaca Broker API",
            iconPath="/static/services/alpaca_broker_api.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
