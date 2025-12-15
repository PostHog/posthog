from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import RedshiftSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RedshiftSource(SimpleSource[RedshiftSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REDSHIFT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.REDSHIFT,
            label="Redshift",
            iconPath="/static/services/redshift.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
