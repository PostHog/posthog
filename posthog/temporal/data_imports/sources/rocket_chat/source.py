from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import RocketChatSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RocketChatSource(SimpleSource[RocketChatSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ROCKETCHAT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ROCKET_CHAT,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Rocket.Chat",
            iconPath="/static/services/rocket_chat.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
