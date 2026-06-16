from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import ZendeskSellSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZendeskSellSource(SimpleSource[ZendeskSellSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZENDESKSELL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZENDESK_SELL,
            category=DataWarehouseSourceCategory.CRM,
            label="Zendesk Sell",
            iconPath="/static/services/zendesk_sell.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
