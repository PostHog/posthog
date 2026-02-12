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
from posthog.temporal.data_imports.sources.generated_configs import LinearSourceConfig
from posthog.temporal.data_imports.sources.linear.linear import (
    linear_source,
    validate_credentials as validate_linear_credentials,
)
from posthog.temporal.data_imports.sources.linear.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LinearSource(SimpleSource[LinearSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LINEAR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LINEAR,
            label="Linear",
            betaSource=True,
            caption="Connect your Linear workspace to sync issues, projects, teams, and more.",
            iconPath="/static/services/linear.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="linear_integration_id",
                        label="Linear account",
                        required=True,
                        kind="linear",
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Linear credentials. Please reconnect your account.",
            "403 Client Error": "Access forbidden. Your token may lack required permissions.",
        }

    def _get_access_token(self, config: LinearSourceConfig, team_id: int) -> str:
        integration = self.get_oauth_integration(config.linear_integration_id, team_id)

        oauth_integration = OauthIntegration(integration)
        if oauth_integration.access_token_expired():
            oauth_integration.refresh_access_token()

        if not integration.access_token:
            raise ValueError("Linear access token not found")
        return integration.access_token

    def get_schemas(self, config: LinearSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

    def validate_credentials(
        self, config: LinearSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            access_token = self._get_access_token(config, team_id)
            return validate_linear_credentials(access_token)
        except Exception as e:
            return False, str(e)

    def source_for_pipeline(self, config: LinearSourceConfig, inputs: SourceInputs) -> SourceResponse:
        access_token = self._get_access_token(config, inputs.team_id)

        return linear_source(
            access_token=access_token,
            endpoint_name=inputs.schema_name,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
