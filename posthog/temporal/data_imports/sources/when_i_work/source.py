from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import WhenIWorkSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WhenIWorkSource(SimpleSource[WhenIWorkSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WHENIWORK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WHEN_I_WORK,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="When I Work",
            iconPath="/static/services/when_i_work.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
