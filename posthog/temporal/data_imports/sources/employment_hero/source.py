from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import EmploymentHeroSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EmploymentHeroSource(SimpleSource[EmploymentHeroSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EMPLOYMENTHERO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EMPLOYMENT_HERO,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Employment-Hero",
            iconPath="/static/services/employment_hero.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
