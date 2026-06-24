from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import TeamtailorSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TeamtailorSource(SimpleSource[TeamtailorSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TEAMTAILOR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TEAMTAILOR,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Teamtailor",
            iconPath="/static/services/teamtailor.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
