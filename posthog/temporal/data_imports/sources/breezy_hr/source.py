from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import BreezyHRSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BreezyHRSource(SimpleSource[BreezyHRSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BREEZYHR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BREEZY_HR,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Breezy HR",
            iconPath="/static/services/breezy_hr.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
