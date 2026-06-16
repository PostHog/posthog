from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SuggestedTable,
)

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import (
    MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
    FieldType,
    ResumableSource,
)
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import BingAdsSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType

from .bing_ads import bing_ads_source, get_incremental_fields, get_schemas
from .utils import BingAdsResumeConfig


@SourceRegistry.register
class BingAdsSource(ResumableSource[BingAdsSourceConfig, BingAdsResumeConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BINGADS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Match only on auth/permission failures that retrying cannot recover from.
        # Transient SDK errors (network, Bing outage, rate limits) propagate as their
        # original exception class and stay retryable — see BingAdsClient.get_customer_id,
        # which wraps the underlying error as `ValueError("Failed to fetch customer ID: <ExcType>: <msg>")`.
        auth_friendly = (
            "PostHog could not authenticate with Bing Ads. The connected account's OAuth credentials "
            "are revoked, expired, or no longer have access. Please reconnect your Bing Ads integration."
        )
        # Specific Azure AD error code surfaced when the tenant lacks a service principal for the
        # Microsoft Advertising API application. Reconnecting won't help — the org admin has to consent
        # on behalf of the tenant — so the generic "reconnect your integration" message is misleading.
        # Must be matched first: the SDK wraps this as `OAuthTokenRequestException: invalid_client AADSTS650052: …`,
        # so both "OAuthTokenRequestException" and "invalid_client" are substrings of the same message —
        # handle_non_retryable picks the first matching dict entry, so AADSTS650052 has to come before both.
        service_principal_friendly = (
            "Your Microsoft tenant has not consented to PostHog's Bing Ads connector "
            "(error AADSTS650052: missing service principal for the Microsoft Advertising API). "
            "Ask a Microsoft 365 administrator to grant admin consent to the application for your tenant, "
            "then reconnect your Bing Ads integration."
        )
        return {
            "AADSTS650052": service_principal_friendly,
            # OAuth grant rejection by Microsoft (the bingads SDK raises OAuthTokenRequestException
            # whose str() format is "<error_code> <error_description>").
            "OAuthTokenRequestException": auth_friendly,
            "invalid_grant": auth_friendly,
            "invalid_client": auth_friendly,
            "unauthorized_client": auth_friendly,
            # Bing Ads service-level auth error codes surfaced via suds.WebFault details
            # (see BingAdsClient.get_customer_id / extract_webfault_detail).
            "AuthenticationTokenExpired": auth_friendly,
            "AuthenticationFailed": auth_friendly,
            "InvalidCredentials": auth_friendly,
            "OAuthTokenExpired": auth_friendly,
            # Bing rejects the SOAP request as invalid *after* auth succeeds — the configured Account ID
            # is wrong or the connected Microsoft Advertising user can't access it. The SDK raises this as
            # `suds.WebFault("Server raised fault: 'Invalid client data. Check the SOAP fault details for
            # more information. TrackingId: <uuid>.'")`. The fault is deterministic (the same bad request
            # always reproduces it), so retrying can't recover — the customer has to fix the Account ID or
            # grant the connected account access. Match the stable phrase only; the TrackingId is volatile.
            # This does not catch transient Bing faults like "Server raised fault: 'Internal Error'".
            "Invalid client data": (
                "Bing Ads rejected the request as invalid. This usually means the configured Account ID is "
                "incorrect, or the connected Bing Ads account does not have access to it. Please check the "
                "Account ID in your source settings and that the connected account can access it, then "
                "reconfigure your Bing Ads source."
            ),
            # Integration row was deleted/disconnected while a scheduled job still references it.
            # Raised by OAuthMixin.get_oauth_integration as `ValueError("Integration not found: <id>")`;
            # the id is volatile, so match only the stable prefix. Retrying can't recreate the row —
            # the customer has to reconnect.
            "Integration not found": "The linked Bing Ads integration no longer exists. Please reconnect your Bing Ads integration.",
            # CustomerManagementService.GetUser returns the generic SOAP fault "Invalid client data.
            # Check the SOAP fault details for more information." when the connected account can't be
            # used — revoked/expired credentials, a work/school identity instead of a personal Microsoft
            # account (WorkIdentityNotAvailable), or no access to the Microsoft Advertising account.
            # GetUser takes no request parameters, so this is never a malformed-request bug on our side;
            # retrying can't recover it. When the specific code above is present in the fault detail it
            # matches first; this catches the generic umbrella message otherwise.
            "Invalid client data": (
                "PostHog could not use the connected Bing Ads account (Microsoft returned 'Invalid client data'). "
                "This usually means the account's credentials are no longer valid, or the Microsoft account does not "
                "have access to the Microsoft Advertising account. Please reconnect your Bing Ads integration and make "
                "sure the signed-in account can access the account in Microsoft Advertising."
            ),
            # Deterministic credential/config errors raised in source_for_pipeline.
            "Bing Ads access token not found": "Bing Ads OAuth access token is missing. Please reconnect your Bing Ads integration.",
            "Bing Ads refresh token not found": "Bing Ads OAuth refresh token is missing. Please reconnect your Bing Ads integration.",
            "Bing Ads developer token not configured": None,
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BING_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["microsoft ads", "microsoft advertising"],
            label="Bing Ads",
            caption="Ensure you have granted PostHog access to your Bing Ads account, learn how to do this in [the documentation](https://posthog.com/docs/cdp/sources/bing-ads).",
            releaseStatus="beta",
            iconPath="/static/services/bing-ads.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/bing-ads",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldOauthConfig(
                        name="bing_ads_integration_id",
                        label="Bing Ads account",
                        required=True,
                        kind="bing-ads",
                    ),
                ],
            ),
            suggestedTables=[
                SuggestedTable(
                    table="campaigns",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
                SuggestedTable(
                    table="campaign_performance_report",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
            ],
        )

    def validate_credentials(
        self, config: BingAdsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not config.account_id or not config.bing_ads_integration_id:
            return False, "Account ID and Bing Ads integration are required"

        if not config.account_id.isdigit():
            return (
                False,
                f"Invalid Account ID '{config.account_id}'. Bing Ads Account IDs are numeric. You can find your Account ID in the Bing Ads dashboard under Settings > Account.",
            )

        try:
            self.get_oauth_integration(config.bing_ads_integration_id, team_id)
            return True, None
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate Bing Ads credentials: {str(e)}"

    def get_schemas(
        self,
        config: BingAdsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        bing_ads_schemas = get_schemas()
        ads_incremental_fields = get_incremental_fields()

        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=ads_incremental_fields.get(endpoint, None) is not None,
                supports_append=ads_incremental_fields.get(endpoint, None) is not None,
                incremental_fields=[
                    {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                    for column_name, column_type in ads_incremental_fields.get(endpoint, [])
                ],
            )
            for endpoint in bing_ads_schemas.keys()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BingAdsResumeConfig]:
        return ResumableSourceManager[BingAdsResumeConfig](inputs, BingAdsResumeConfig)

    def source_for_pipeline(
        self,
        config: BingAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[BingAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        integration = self.get_oauth_integration(config.bing_ads_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"Bing Ads access token not found for job {inputs.job_id}")
        if not integration.refresh_token:
            raise ValueError(f"Bing Ads refresh token not found for job {inputs.job_id}")

        return bing_ads_source(
            account_id=config.account_id,
            resource_name=inputs.schema_name,
            access_token=integration.access_token,
            refresh_token=integration.refresh_token,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_type=inputs.incremental_field_type if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
