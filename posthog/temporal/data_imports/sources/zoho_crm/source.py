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
from posthog.temporal.data_imports.sources.generated_configs import ZohoCrmSourceConfig
from posthog.temporal.data_imports.sources.zoho_crm.auth import zoho_crm_refresh_access_token
from posthog.temporal.data_imports.sources.zoho_crm.settings import (
    ENDPOINTS as ZOHO_CRM_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from posthog.temporal.data_imports.sources.zoho_crm.zoho_crm import (
    validate_credentials as validate_zoho_crm_credentials,
    zoho_crm_source,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZohoCrmSource(SimpleSource[ZohoCrmSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOHOCRM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZOHO_CRM,
            caption="""Select an existing Zoho CRM account to link to PostHog or create a new connection.

Note: Currently supports US data center only. Contact support for other regions.""",
            iconPath="/static/services/zoho-crm.png",
            docsUrl="https://posthog.com/docs/cdp/sources/zoho-crm",
            feature_flag="dwh_zoho_crm",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="zoho_crm_integration_id",
                        label="Zoho CRM account",
                        required=True,
                        kind="zoho-crm",
                    ),
                ],
            ),
        )

    def get_schemas(self, config: ZohoCrmSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=True,
                supports_append=True,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ZOHO_CRM_ENDPOINTS
        ]

    def validate_credentials(self, config: ZohoCrmSourceConfig, team_id: int) -> tuple[bool, str | None]:
        integration = self.get_oauth_integration(config.zoho_crm_integration_id, team_id)

        access_token = integration.access_token
        refresh_token = integration.refresh_token

        # Use US domains by default
        # TODO: Support other regions by adding separate integration kinds
        accounts_domain = integration.config.get("accounts_domain", "https://accounts.zoho.com")
        api_domain = integration.config.get("api_domain", "https://www.zohoapis.com")

        if not refresh_token:
            return False, "Zoho CRM refresh token not found"

        # Refresh token if needed
        if not access_token:
            try:
                access_token = zoho_crm_refresh_access_token(refresh_token, accounts_domain)
            except Exception as e:
                return False, f"Failed to refresh Zoho CRM access token: {str(e)}"

        # Validate credentials
        if validate_zoho_crm_credentials(access_token, api_domain):
            return True, None
        else:
            return False, "Invalid Zoho CRM credentials"

    def source_for_pipeline(self, config: ZohoCrmSourceConfig, inputs: SourceInputs) -> SourceResponse:
        integration = self.get_oauth_integration(config.zoho_crm_integration_id, inputs.team_id)

        access_token = integration.access_token
        refresh_token = integration.refresh_token

        # Use US domains by default
        # TODO: Support other regions by adding separate integration kinds
        accounts_domain = integration.config.get("accounts_domain", "https://accounts.zoho.com")
        api_domain = integration.config.get("api_domain", "https://www.zohoapis.com")

        if not refresh_token:
            raise ValueError(f"Zoho CRM refresh token not found for job {inputs.job_id}")

        # Refresh access token if needed
        if not access_token:
            access_token = zoho_crm_refresh_access_token(refresh_token, accounts_domain)

        return zoho_crm_source(
            access_token=access_token,
            api_domain=api_domain,
            module=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            logger=inputs.logger,
        )
