from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import PabblySubscriptionsBillingSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PabblySubscriptionsBillingSource(SimpleSource[PabblySubscriptionsBillingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PABBLYSUBSCRIPTIONSBILLING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PABBLY_SUBSCRIPTIONS_BILLING,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Pabbly Subscriptions Billing",
            iconPath="/static/services/pabbly_subscriptions_billing.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
