from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import InforNexusSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class InforNexusSource(SimpleSource[InforNexusSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INFORNEXUS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INFOR_NEXUS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Infor Nexus",
            iconPath="/static/services/infor_nexus.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
