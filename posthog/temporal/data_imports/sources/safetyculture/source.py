from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import SafetyCultureSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SafetyCultureSource(SimpleSource[SafetyCultureSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAFETYCULTURE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SAFETY_CULTURE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="SafetyCulture",
            iconPath="/static/services/safetyculture.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
