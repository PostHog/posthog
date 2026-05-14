from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldOauthConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import SalesforceSourceConfig
from posthog.temporal.data_imports.sources.salesforce.auth import salesforce_refresh_access_token
from posthog.temporal.data_imports.sources.salesforce.salesforce import SalesforceResumeConfig, salesforce_source
from posthog.temporal.data_imports.sources.salesforce.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SalesforceSource(ResumableSource[SalesforceSourceConfig, SalesforceResumeConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SALESFORCE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "invalid_session_id": "Your Salesforce session has expired. Please reconnect the source.",
            "400 Client Error: Bad Request for url": None,
            "403 Client Error: Forbidden for url": None,
            "inactive organization": None,
        }

    def get_schemas(
        self, config: SalesforceSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SALESFORCE,
            caption="Select an existing Salesforce account to link to PostHog or create a new connection",
            iconPath="/static/services/salesforce.png",
            docsUrl="https://posthog.com/docs/cdp/sources/salesforce",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="salesforce_integration_id", label="Salesforce account", required=True, kind="salesforce"
                    )
                ],
            ),
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SalesforceResumeConfig]:
        return ResumableSourceManager[SalesforceResumeConfig](inputs, SalesforceResumeConfig)

    def source_for_pipeline(
        self,
        config: SalesforceSourceConfig,
        resumable_source_manager: ResumableSourceManager[SalesforceResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        integration = self.get_oauth_integration(config.salesforce_integration_id, inputs.team_id)

        salesforce_refresh_token = integration.refresh_token

        if not salesforce_refresh_token:
            raise ValueError(f"Salesforce refresh token not found for job {inputs.job_id}")

        salesforce_access_token = integration.access_token
        salesforce_instance_url = integration.config.get("instance_url")

        if not salesforce_access_token:
            salesforce_access_token = salesforce_refresh_access_token(salesforce_refresh_token, salesforce_instance_url)

        resource = salesforce_source(
            instance_url=salesforce_instance_url,
            access_token=salesforce_access_token,
            refresh_token=salesforce_refresh_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=["id"] if inputs.should_use_incremental_field else None,
            column_hints=resource.column_hints,
        )
