from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import AssemblyAISourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AssemblyAISource(SimpleSource[AssemblyAISourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ASSEMBLYAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ASSEMBLY_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AssemblyAI",
            iconPath="/static/services/assemblyai.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
