from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import CloudbedsSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CloudbedsSource(SimpleSource[CloudbedsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOUDBEDS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLOUDBEDS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Cloudbeds",
            iconPath="/static/services/cloudbeds.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
