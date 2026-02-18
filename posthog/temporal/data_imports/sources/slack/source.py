from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldOauthConfig,
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
            betaSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="slack_integration_id",
                        label="Slack workspace",
                        required=True,
                        kind="slack",
                        requiredScopes="channels:read groups:read channels:history groups:history users:read users:read.email reactions:read",
                    )
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "invalid_auth": "Your Slack token is invalid. Please reconnect the source.",
            "account_inactive": "Your Slack account is inactive. Please reconnect the source.",
            "token_revoked": "Your Slack token has been revoked. Please reconnect the source.",
            "missing_scope": "Your Slack integration is missing required scopes. Please reconnect the source.",
            "not_in_channel": "The Slack bot is not a member of this channel. Please invite the bot to the channel and try again.",
            "channel_not_found": "This Slack channel was not found. It may have been deleted or the bot lacks permission to access it.",
        }

    def get_schemas(self, config: SlackSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        schemas: list[SourceSchema] = [
            SourceSchema(
                name=name,
                supports_incremental=len(endpoint_config.incremental_fields) > 0,
                supports_append=len(endpoint_config.incremental_fields) > 0,
                incremental_fields=endpoint_config.incremental_fields,
            )
            for name, endpoint_config in ENDPOINTS.items()
        ]

        integration = self.get_oauth_integration(config.slack_integration_id, team_id)
        access_token = integration.access_token
        if access_token:
            msg_config = messages_endpoint_config()
            channels = get_channels(access_token)
            for ch in channels:
                schemas.append(
                    SourceSchema(
                        name=ch["name"],
                        supports_incremental=len(msg_config.incremental_fields) > 0,
                        supports_append=len(msg_config.incremental_fields) > 0,
                        incremental_fields=msg_config.incremental_fields,
                    )
                )

        return schemas

    def validate_credentials(
        self, config: SlackSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        integration = self.get_oauth_integration(config.slack_integration_id, team_id)
        access_token = integration.access_token

        if not access_token:
            return False, "Slack access token not found"

        if validate_slack_credentials(access_token):
            return True, None

        return False, "Invalid Slack credentials"

    def source_for_pipeline(self, config: SlackSourceConfig, inputs: SourceInputs) -> SourceResponse:
        integration = self.get_oauth_integration(config.slack_integration_id, inputs.team_id)
        access_token = integration.access_token

        if not access_token:
            raise ValueError(f"Slack access token not found for job {inputs.job_id}")

        return slack_source(
            access_token=access_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
