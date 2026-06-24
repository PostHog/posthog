from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import ZohoBillingSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZohoBillingSource(SimpleSource[ZohoBillingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOHOBILLING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZOHO_BILLING,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Zoho Billing",
            iconPath="/static/services/zoho_billing.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
