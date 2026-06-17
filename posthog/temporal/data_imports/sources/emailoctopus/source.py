from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import EmailOctopusSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EmailOctopusSource(SimpleSource[EmailOctopusSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EMAILOCTOPUS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EMAIL_OCTOPUS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="EmailOctopus",
            iconPath="/static/services/emailoctopus.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
