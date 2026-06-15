from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import Db2SourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Db2Source(SimpleSource[Db2SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DB2

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DB2,
            label="IBM Db2",
            iconPath="/static/services/db2.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
