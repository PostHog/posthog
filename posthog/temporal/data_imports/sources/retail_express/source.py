from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import RetailExpressSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RetailExpressSource(SimpleSource[RetailExpressSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RETAILEXPRESS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RETAIL_EXPRESS,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Retail Express",
            iconPath="/static/services/retail_express.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
