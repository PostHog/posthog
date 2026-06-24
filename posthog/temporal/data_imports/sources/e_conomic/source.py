from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import EConomicSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EConomicSource(SimpleSource[EConomicSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ECONOMIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.E_CONOMIC,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="e-conomic",
            iconPath="/static/services/e_conomic.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
