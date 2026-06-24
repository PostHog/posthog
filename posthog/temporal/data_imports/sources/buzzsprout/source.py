from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import BuzzsproutSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BuzzsproutSource(SimpleSource[BuzzsproutSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BUZZSPROUT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BUZZSPROUT,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Buzzsprout",
            iconPath="/static/services/buzzsprout.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
