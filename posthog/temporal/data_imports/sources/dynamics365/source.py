from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import Dynamics365SourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Dynamics365Source(SimpleSource[Dynamics365SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DYNAMICS365

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DYNAMICS365,
            label="Microsoft Dynamics 365",
            iconPath="/static/services/dynamics365.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
