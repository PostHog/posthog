from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import SparkPostSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SparkPostSource(SimpleSource[SparkPostSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPARKPOST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SPARK_POST,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="SparkPost",
            iconPath="/static/services/sparkpost.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
