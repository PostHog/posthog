from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import SlackSourceConfig
from posthog.temporal.data_imports.sources.slack.settings import ENDPOINTS, messages_endpoint_config
from posthog.temporal.data_imports.sources.slack.slack import (
    get_channels,
    slack_source,
    validate_credentials as validate_slack_credentials,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SlackSource(SimpleSource[SlackSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SLACK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SLACK,
            caption="Select an existing Slack workspace to link to PostHog or create a new connection",
            iconPath="/static/services/slack.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
