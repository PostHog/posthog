from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import CodefreshSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CodefreshSource(SimpleSource[CodefreshSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CODEFRESH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CODEFRESH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Codefresh",
            iconPath="/static/services/codefresh.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
