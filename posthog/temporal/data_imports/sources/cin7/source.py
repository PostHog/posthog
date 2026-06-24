from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import Cin7SourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Cin7Source(SimpleSource[Cin7SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CIN7

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CIN7,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Cin7",
            iconPath="/static/services/cin7.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
