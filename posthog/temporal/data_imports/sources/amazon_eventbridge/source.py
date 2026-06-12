from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import AmazonEventBridgeSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AmazonEventBridgeSource(SimpleSource[AmazonEventBridgeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONEVENTBRIDGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AMAZON_EVENT_BRIDGE,
            label="Amazon EventBridge",
            iconPath="/static/services/amazon_eventbridge.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
