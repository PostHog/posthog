from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import MissiveSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MissiveSource(SimpleSource[MissiveSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MISSIVE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MISSIVE,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Missive",
            iconPath="/static/services/missive.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
