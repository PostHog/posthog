from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import AcuitySchedulingSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AcuitySchedulingSource(SimpleSource[AcuitySchedulingSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ACUITYSCHEDULING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ACUITY_SCHEDULING,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Acuity Scheduling",
            iconPath="/static/services/acuity_scheduling.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
