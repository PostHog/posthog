from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import StreamlabsSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class StreamlabsSource(SimpleSource[StreamlabsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STREAMLABS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.STREAMLABS,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            keywords=["twitch", "streaming"],
            label="Streamlabs",
            iconPath="/static/services/streamlabs.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
