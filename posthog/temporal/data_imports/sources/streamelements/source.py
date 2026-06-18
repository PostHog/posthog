from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import StreamElementsSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class StreamElementsSource(SimpleSource[StreamElementsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STREAMELEMENTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.STREAM_ELEMENTS,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            keywords=["twitch", "streaming"],
            label="StreamElements",
            iconPath="/static/services/streamelements.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
