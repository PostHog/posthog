from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import ThriveLearningSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ThriveLearningSource(SimpleSource[ThriveLearningSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.THRIVELEARNING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.THRIVE_LEARNING,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Thrive Learning",
            iconPath="/static/services/thrive_learning.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
