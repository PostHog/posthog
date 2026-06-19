from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import ElasticemailSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ElasticemailSource(SimpleSource[ElasticemailSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ELASTICEMAIL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ELASTICEMAIL,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Elasticemail",
            iconPath="/static/services/elasticemail.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
