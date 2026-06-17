from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import FreeAgentSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FreeAgentSource(SimpleSource[FreeAgentSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FREEAGENT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FREE_AGENT,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="FreeAgent",
            iconPath="/static/services/freeagent.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
