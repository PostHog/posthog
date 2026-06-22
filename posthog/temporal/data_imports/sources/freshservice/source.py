from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import FreshserviceSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FreshserviceSource(SimpleSource[FreshserviceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FRESHSERVICE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FRESHSERVICE,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Freshservice",
            iconPath="/static/services/freshservice.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
