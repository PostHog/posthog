from typing import TYPE_CHECKING, Optional, cast

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import (
    FieldType,
    ResumableSource,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSource,
)
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.common.webhook_s3 import (
    WebhookSourceManager,
    is_webhook_feature_flag_enabled,
)
from posthog.temporal.data_imports.sources.generated_configs import SlackSourceConfig
from posthog.temporal.data_imports.sources.slack.settings import ENDPOINTS, messages_endpoint_config
from posthog.temporal.data_imports.sources.slack.slack import (
    SlackResumeConfig,
    get_channels,
    slack_source,
    validate_credentials as validate_slack_credentials,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SlackSource(ResumableSource[SlackSourceConfig, SlackResumeConfig], WebhookSource[SlackSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SLACK

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from posthog.temporal.data_imports.sources.slack.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        # Slack channel IDs are used as both schema names and webhook event keys,
        # so this is an identity mapping. We return an empty dict and rely on the
        # fallback in get_or_create_webhook_hog_function that defaults to using
        # the schema name as the object type.
        return {}

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(self, config: SlackSourceConfig, webhook_url: str, team_id: int) -> WebhookCreationResult:
        return WebhookCreationResult(
            success=False,
            error="Slack does not support automatic webhook creation. Please follow the manual setup instructions.",
        )

    def delete_webhook(self, config: SlackSourceConfig, webhook_url: str, team_id: int) -> WebhookDeletionResult:
        # Slack does not expose an API to remove an Events API Request URL — the user has to
        # toggle it off manually in the app settings. Returning success lets the HogFunction
        # be cleaned up without showing the user a misleading "deletion failed" error.
        return WebhookDeletionResult(success=True)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SLACK,
            caption="Connect your Slack workspace to sync channels, users, and messages.",
            iconPath="/static/services/slack.png",
            featureFlag="slack-dwh",
            unreleasedSource=True,
            releaseStatus="alpha",
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
            webhookManualOnly=True,
            webhookSetupCaption="""Use the manifest below to create a Slack app with the webhook URL and event subscriptions already configured.

1. Open [Slack apps](https://api.slack.com/apps?new_app=1) and click **From a manifest**
2. Pick your workspace and click **Next**
3. Paste the manifest below into the editor, click **Next**, then **Create**
4. In the left sidebar, click **Install App**, then **Install to Workspace**, and authorize
5. Open **Basic information > App credentials**, copy the **Signing secret**, and paste it in the form below

```json
{
    "display_information": {
        "name": "PostHog data warehouse",
        "description": "Sync Slack messages and channels to PostHog data warehouse"
    },
    "oauth_config": {
        "scopes": {
            "user": [
                "channels:history",
                "groups:history"
            ]
        }
    },
    "settings": {
        "event_subscriptions": {
            "request_url": "{webhook_url}",
            "user_events": [
                "message.channels",
                "message.groups"
            ]
        },
        "org_deploy_enabled": false,
        "socket_mode_enabled": false,
        "token_rotation_enabled": false
    }
}
```""",
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    ),
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
        webhook_flag_enabled = is_webhook_feature_flag_enabled(team_id)
        authed_user = (integration.config or {}).get("authed_user", {}).get("id")
        channels = get_channels(access_token, authed_user)
        for ch in channels:
            if ch["id"] in ENDPOINTS:
                continue
            schemas.append(
                SourceSchema(
                    name=ch["id"],
                    label=ch["name"],
                    supports_incremental=len(msg_config.incremental_fields) > 0,
                    supports_webhooks=webhook_flag_enabled,
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

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SlackResumeConfig]:
        return ResumableSourceManager[SlackResumeConfig](inputs, SlackResumeConfig)

    def source_for_pipeline(
        self,
        config: SlackSourceConfig,
        resumable_source_manager: ResumableSourceManager[SlackResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        integration = self.get_oauth_integration(config.slack_integration_id, inputs.team_id)
        access_token = integration.access_token

        if not access_token:
            raise ValueError(f"Slack access token not found for job {inputs.job_id}")

        # For channel schemas, the schema name is the channel ID itself
        channel_id = inputs.schema_name if inputs.schema_name not in ENDPOINTS else None

        webhook_source_manager = self.get_webhook_source_manager(inputs)

        return slack_source(
            access_token=access_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
            channel_id=channel_id,
            webhook_source_manager=webhook_source_manager,
        )
