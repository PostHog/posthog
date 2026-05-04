from typing import cast

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
from posthog.temporal.data_imports.sources.generated_configs import IntercomSourceConfig
from posthog.temporal.data_imports.sources.intercom.intercom import (
    intercom_source,
    validate_credentials as validate_intercom_credentials,
)
from posthog.temporal.data_imports.sources.intercom.settings import INTERCOM_ENDPOINTS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class IntercomSource(SimpleSource[IntercomSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INTERCOM

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Intercom connection is invalid or expired. Please reconnect it.",
            "403 Client Error": "Your Intercom connection is missing required scopes. Please update permissions and reconnect.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INTERCOM,
            caption="Select an existing Intercom workspace to link to PostHog or create a new connection",
            iconPath="/static/services/intercom.png",
            docsUrl="https://posthog.com/docs/cdp/sources/intercom",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="intercom_integration_id",
                        label="Intercom workspace",
                        required=True,
                        kind="intercom",
                    ),
                ],
            ),
            featureFlag="dwh_intercom",
        )

    def get_schemas(
        self,
        config: IntercomSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint_config in INTERCOM_ENDPOINTS.values()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: IntercomSourceConfig, team_id: int, schema_name: str | None = None
    ) -> tuple[bool, str | None]:
        try:
            integration = self.get_oauth_integration(config.intercom_integration_id, team_id)
        except ValueError as e:
            return False, str(e)

        if not integration.access_token:
            return False, "Intercom integration has no access token. Please reconnect."

        return validate_intercom_credentials(integration.access_token)

    def source_for_pipeline(self, config: IntercomSourceConfig, inputs: SourceInputs) -> SourceResponse:
        integration = self.get_oauth_integration(config.intercom_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"Intercom access token not found for job {inputs.job_id}")

        return intercom_source(
            access_token=integration.access_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )
