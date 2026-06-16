from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import NebiusAISourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NebiusAISource(SimpleSource[NebiusAISourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEBIUSAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NEBIUS_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Nebius AI",
            iconPath="/static/services/nebius_ai.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
