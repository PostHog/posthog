from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import CastorEDCSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CastorEDCSource(SimpleSource[CastorEDCSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CASTOREDC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CASTOR_EDC,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Castor EDC",
            iconPath="/static/services/castor_edc.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
