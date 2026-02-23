from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldOauthConfig,
)

from posthog.models.integration import OauthIntegration
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import IntercomSourceConfig
from posthog.temporal.data_imports.sources.intercom.intercom import (
    intercom_source,
    validate_credentials as validate_intercom_credentials,
)
from posthog.temporal.data_imports.sources.intercom.settings import INCREMENTAL_FIELDS, INTERCOM_ENDPOINTS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class IntercomSource(SimpleSource[IntercomSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INTERCOM

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.intercom.io": "Your Intercom credentials are invalid or expired. Please reconnect your account.",
            "403 Client Error: Forbidden for url: https://api.intercom.io": "Your Intercom account does not have the required permissions. Please check your app scopes and try again.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INTERCOM,
            label="Intercom",
            caption="Connect your Intercom account to automatically pull contacts, companies, conversations, and more into the PostHog Data warehouse.",
            iconPath="/static/services/intercom.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="intercom_integration_id",
                        label="Intercom account",
                        required=True,
                        kind="intercom",
                    ),
                ],
            ),
        )

    def _get_access_token(self, config: IntercomSourceConfig, team_id: int) -> str:
        integration = self.get_oauth_integration(config.intercom_integration_id, team_id)

        oauth_integration = OauthIntegration(integration)
        if oauth_integration.access_token_expired():
            oauth_integration.refresh_access_token()

        if not integration.access_token:
            raise ValueError("Intercom access token not found")
        return integration.access_token

    def get_schemas(self, config: IntercomSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=endpoint_config.name in INCREMENTAL_FIELDS,
                supports_append=endpoint_config.name in INCREMENTAL_FIELDS,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint_config.name, []),
            )
            for endpoint_config in INTERCOM_ENDPOINTS.values()
        ]

    def validate_credentials(
        self, config: IntercomSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            access_token = self._get_access_token(config, team_id)
            return validate_intercom_credentials(access_token)
        except Exception as e:
            return False, str(e)

    def source_for_pipeline(self, config: IntercomSourceConfig, inputs: SourceInputs) -> SourceResponse:
        access_token = self._get_access_token(config, inputs.team_id)

        return intercom_source(
            api_key=access_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
