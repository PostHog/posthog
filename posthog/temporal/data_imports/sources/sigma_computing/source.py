from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import SigmaComputingSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SigmaComputingSource(SimpleSource[SigmaComputingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SIGMACOMPUTING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SIGMA_COMPUTING,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Sigma Computing",
            iconPath="/static/services/sigma_computing.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
