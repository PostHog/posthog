from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import AdobeCommerceSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AdobeCommerceSource(SimpleSource[AdobeCommerceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ADOBECOMMERCE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ADOBE_COMMERCE,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            keywords=["magento"],
            label="Adobe Commerce (Magento)",
            iconPath="/static/services/adobe_commerce.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
