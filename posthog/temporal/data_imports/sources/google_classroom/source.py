from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import GoogleClassroomSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleClassroomSource(SimpleSource[GoogleClassroomSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLECLASSROOM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_CLASSROOM,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Google Classroom",
            iconPath="/static/services/google_classroom.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
