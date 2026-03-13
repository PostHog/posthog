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
            caption="Connect your Slack workspace to sync channels, users, and messages.",
            iconPath="/static/services/slack.png",
            featureFlag="slack-dwh",
            unreleasedSource=True,
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
            "Integration not found": "Your Slack integration was not found. Please reconnect the source.",
            "Slack access token not found": "Your Slack access token is missing. Please reconnect the source.",
        }

    def get_schemas(
        self, config: SlackSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
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
        if not access_token:
            raise ValueError("Slack access token not found")

        msg_config = messages_endpoint_config()
        channels = get_channels(access_token)
        for ch in channels:
            if ch["id"] in ENDPOINTS:
                continue
            schemas.append(
                SourceSchema(
                    name=ch["id"],
                    label=ch["name"],
                    supports_incremental=len(msg_config.incremental_fields) > 0,
                    supports_append=len(msg_config.incremental_fields) > 0,
                    incremental_fields=msg_config.incremental_fields,
                )
            )

        return schemas

    def validate_credentials(
        self, config: SlackSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            integration = self.get_oauth_integration(config.slack_integration_id, team_id)
            access_token = integration.access_token

            if not access_token:
                return False, "Slack access token not found"

            if validate_slack_credentials(access_token):
                return True, None

            return False, "Invalid Slack credentials"
        except Exception as e:
            return False, f"Failed to validate Slack credentials: {str(e)}"

    def source_for_pipeline(self, config: SlackSourceConfig, inputs: SourceInputs) -> SourceResponse:
        integration = self.get_oauth_integration(config.slack_integration_id, inputs.team_id)
        access_token = integration.access_token

        if not access_token:
            raise ValueError(f"Slack access token not found for job {inputs.job_id}")

        # For channel schemas, the schema name is the channel ID itself
        channel_id = inputs.schema_name if inputs.schema_name not in ENDPOINTS else None

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
            channel_id=channel_id,
        )
