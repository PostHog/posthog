from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import WikipediaPageviewsSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WikipediaPageviewsSource(SimpleSource[WikipediaPageviewsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WIKIPEDIAPAGEVIEWS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WIKIPEDIA_PAGEVIEWS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Wikipedia Pageviews",
            iconPath="/static/services/wikipedia_pageviews.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
