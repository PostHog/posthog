from typing import cast
from posthog.schema import (
    ExternalDataSourceType,
    SourceConfig,
)
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import MailjetSourceConfig
from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class MailJetSource(BaseSource[MailjetSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.MAILJET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MAILJET,
            label="Mailjet",
            caption="",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
