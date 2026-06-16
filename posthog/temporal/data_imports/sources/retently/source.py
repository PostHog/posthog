from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import RetentlySourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RetentlySource(SimpleSource[RetentlySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RETENTLY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RETENTLY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Retently",
            iconPath="/static/services/retently.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
