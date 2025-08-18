from typing import cast
from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import KlaviyoSourceConfig
from posthog.warehouse.types import ExternalDataSourceType


@SourceRegistry.register
class KlaviyoSource(BaseSource[KlaviyoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KLAVIYO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KLAVIYO,
            label="Klaviyo",
            caption="",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
