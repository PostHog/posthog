from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import OpenDataDcSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OpenDataDcSource(SimpleSource[OpenDataDcSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENDATADC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPEN_DATA_DC,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Open Data DC",
            iconPath="/static/services/open_data_dc.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
