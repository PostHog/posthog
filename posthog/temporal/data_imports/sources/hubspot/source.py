from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldOauthConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common import config
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import HubspotSourceConfig
from posthog.temporal.data_imports.sources.hubspot.auth import hubspot_refresh_access_token
from posthog.temporal.data_imports.sources.hubspot.hubspot import HubspotResumeConfig, hubspot_source
from posthog.temporal.data_imports.sources.hubspot.settings import ENDPOINTS as HUBSPOT_ENDPOINTS

from products.data_warehouse.backend.types import ExternalDataSourceType


@config.config
class HubspotSourceOldConfig(config.Config):
    hubspot_secret_key: str | None = None
    hubspot_refresh_token: str | None = None


@SourceRegistry.register
class HubspotSource(ResumableSource[HubspotSourceConfig | HubspotSourceOldConfig, HubspotResumeConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HUBSPOT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HUBSPOT,
            caption="Select an existing Hubspot account to link to PostHog or create a new connection",
            iconPath="/static/services/hubspot.png",
            docsUrl="https://posthog.com/docs/cdp/sources/hubspot",
            featured=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="hubspot_integration_id", label="Hubspot account", required=True, kind="hubspot"
                    )
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "missing or invalid refresh token": "Your HubSpot connection is invalid or expired. Please reconnect it.",
            "missing or unknown hub id": None,
        }

    # TODO: clean up hubspot job inputs to not have two auth config options
    def parse_config(self, job_inputs: dict) -> HubspotSourceConfig | HubspotSourceOldConfig:
        if "hubspot_integration_id" in job_inputs.keys():
            return self._config_class.from_dict(job_inputs)

        return HubspotSourceOldConfig.from_dict(job_inputs)

    def get_schemas(
        self,
        config: HubspotSourceConfig | HubspotSourceOldConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in HUBSPOT_ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HubspotResumeConfig]:
        return ResumableSourceManager[HubspotResumeConfig](inputs, HubspotResumeConfig)

    def source_for_pipeline(
        self,
        config: HubspotSourceConfig | HubspotSourceOldConfig,
        resumable_source_manager: ResumableSourceManager[HubspotResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if isinstance(config, HubspotSourceConfig):
            integration = self.get_oauth_integration(config.hubspot_integration_id, inputs.team_id)

            if not integration.access_token or not integration.refresh_token:
                raise ValueError(f"Hubspot refresh or access token not found for job {inputs.job_id}")

            hubspot_access_code = integration.access_token
            refresh_token = integration.refresh_token
        else:
            config_hubspot_access_code = config.hubspot_secret_key
            config_refresh_token = config.hubspot_refresh_token

            if not config_refresh_token:
                raise ValueError(f"Hubspot refresh token not found for job {inputs.job_id}")
            else:
                refresh_token = config_refresh_token

            if not config_hubspot_access_code:
                hubspot_access_code = hubspot_refresh_access_token(refresh_token)
            else:
                hubspot_access_code = config_hubspot_access_code

        return hubspot_source(
            api_key=hubspot_access_code,
            refresh_token=refresh_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
