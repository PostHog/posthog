from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import YoutubeDataSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class YoutubeDataSource(SimpleSource[YoutubeDataSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YOUTUBEDATA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.YOUTUBE_DATA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Youtube Data",
            iconPath="/static/services/youtube_data.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
