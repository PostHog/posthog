from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import ShutterstockSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ShutterstockSource(SimpleSource[ShutterstockSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHUTTERSTOCK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SHUTTERSTOCK,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Shutterstock",
            iconPath="/static/services/shutterstock.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
