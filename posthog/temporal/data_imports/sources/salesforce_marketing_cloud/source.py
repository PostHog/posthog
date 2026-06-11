from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import SalesforceMarketingCloudSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SalesforceMarketingCloudSource(SimpleSource[SalesforceMarketingCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SALESFORCEMARKETINGCLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SALESFORCE_MARKETING_CLOUD,
            label="Salesforce Marketing Cloud",
            iconPath="/static/services/salesforce_marketing_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
