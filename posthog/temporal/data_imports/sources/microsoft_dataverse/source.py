from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import MicrosoftDataverseSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MicrosoftDataverseSource(SimpleSource[MicrosoftDataverseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTDATAVERSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MICROSOFT_DATAVERSE,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Microsoft Dataverse",
            iconPath="/static/services/microsoft_dataverse.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
