from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import GainsightPxSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GainsightPxSource(SimpleSource[GainsightPxSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GAINSIGHTPX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GAINSIGHT_PX,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Gainsight Px",
            iconPath="/static/services/gainsight_px.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
