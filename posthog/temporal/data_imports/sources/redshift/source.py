from typing import cast
from posthog.schema import (
    ExternalDataSourceType,
    SourceConfig,
)
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import RedshiftSourceConfig
from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class RedshiftSource(BaseSource[RedshiftSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.REDSHIFT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.REDSHIFT,
            label="Redshift",
            caption="",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
