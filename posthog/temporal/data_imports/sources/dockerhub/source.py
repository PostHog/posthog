from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import DockerhubSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DockerhubSource(SimpleSource[DockerhubSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DOCKERHUB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DOCKERHUB,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Dockerhub",
            iconPath="/static/services/dockerhub.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
