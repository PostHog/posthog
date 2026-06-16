from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import JobNimbusSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class JobNimbusSource(SimpleSource[JobNimbusSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JOBNIMBUS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.JOB_NIMBUS,
            category=DataWarehouseSourceCategory.CRM,
            label="JobNimbus",
            iconPath="/static/services/jobnimbus.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
