from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import MailchimpSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MailchimpSource(BaseSource[MailchimpSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MAILCHIMP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MAILCHIMP,
            label="Mailchimp",
            iconPath="/static/services/mailchimp.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mailchimp",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
