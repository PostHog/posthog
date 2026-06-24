from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import ThinkificCoursesSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ThinkificCoursesSource(SimpleSource[ThinkificCoursesSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.THINKIFICCOURSES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.THINKIFIC_COURSES,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Thinkific Courses",
            iconPath="/static/services/thinkific_courses.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
