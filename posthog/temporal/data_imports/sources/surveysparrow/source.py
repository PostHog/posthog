from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import SurveySparrowSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SurveySparrowSource(SimpleSource[SurveySparrowSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SURVEYSPARROW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SURVEY_SPARROW,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="SurveySparrow",
            iconPath="/static/services/surveysparrow.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
