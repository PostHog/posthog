import re
from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSwitchGroupConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import GoogleAdsSourceConfig
from posthog.temporal.data_imports.sources.google_ads.google_ads import (
    GoogleAdsServiceAccountSourceConfig,
    clean_customer_id,
    get_incremental_fields as get_google_ads_incremental_fields,
    get_schemas as get_google_ads_schemas,
    google_ads_client,
    google_ads_source,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleAdsSource(SimpleSource[GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig], OAuthMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEADS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "PERMISSION_DENIED": None,
            "UNAUTHENTICATED": None,
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT": None,
            "Account has been deleted": None,
            "INVALID_CUSTOMER_ID": None,
        }

    # TODO: clean up google ads source to not have two auth config options
    def parse_config(self, job_inputs: dict) -> GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig:
        if "google_ads_integration_id" in job_inputs.keys():
            return self._config_class.from_dict(job_inputs)

        return GoogleAdsServiceAccountSourceConfig.from_dict(job_inputs)

    def get_schemas(
        self,
        config: GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig,
        team_id: int,
        with_counts: bool = False,
    ) -> list[SourceSchema]:
        google_ads_schemas = get_google_ads_schemas(
            config,
            team_id,
        )

        ads_incremental_fields = get_google_ads_incremental_fields()

        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=ads_incremental_fields.get(endpoint, None) is not None,
                supports_append=ads_incremental_fields.get(endpoint, None) is not None,
                incremental_fields=[
                    {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                    for column_name, column_type in ads_incremental_fields.get(endpoint, [])
                ],
            )
            for endpoint in google_ads_schemas.keys()
        ]

    def source_for_pipeline(
        self, config: GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig, inputs: SourceInputs
    ) -> SourceResponse:
        return google_ads_source(
            config=config,
            resource_name=inputs.schema_name,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_type=inputs.incremental_field_type if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_ADS,
            label="Google Ads",
            caption="Ensure you have granted PostHog access to your Google Ads account, learn how to do this in [the docs](https://posthog.com/docs/cdp/sources/google-ads).",
            betaSource=True,
            iconPath="/static/services/google-ads.png",
            docsUrl="https://posthog.com/docs/cdp/sources/google-ads",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="customer_id",
                        label="Customer ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123-456-7890",
                    ),
                    SourceFieldOauthConfig(
                        name="google_ads_integration_id", label="Google Ads account", required=True, kind="google-ads"
                    ),
                    SourceFieldSwitchGroupConfig(
                        name="is_mcc_account",
                        label="Using MCC account?",
                        caption="Whether your account is a Google Ads MCC account and you're accessing a clients account?",
                        default=False,
                        fields=cast(
                            list[FieldType],
                            [
                                SourceFieldInputConfig(
                                    name="mcc_client_id",
                                    label="Managers customer ID",
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=True,
                                    placeholder="123-456-7890",
                                )
                            ],
                        ),
                    ),
                ],
            ),
        )

    def validate_config(self, job_inputs: dict) -> tuple[bool, list[str]]:
        is_valid, errors = super().validate_config(job_inputs)

        customer_id = job_inputs.get("customer_id", "")
        if customer_id and not re.match(r"^\d{3}-\d{3}-\d{4}$", customer_id):
            errors.append(
                "Please enter a valid Google Ads customer ID. This should be 10-digits and in XXX-XXX-XXXX format."
            )
            is_valid = False

        is_mcc_account = job_inputs.get("is_mcc_account", {})
        if is_mcc_account.get("enabled"):
            mcc_client_id = is_mcc_account.get("mcc_client_id", "")
            if mcc_client_id and not re.match(r"^\d{3}-\d{3}-\d{4}$", mcc_client_id):
                errors.append(
                    "Please enter a valid Google Ads manager customer ID. This should be 10-digits and in XXX-XXX-XXXX format."
                )
                is_valid = False

        return is_valid, errors

    def _validate_mcc_customer_access(self, client, config: GoogleAdsSourceConfig) -> tuple[bool, str | None]:
        """Validate that a client account is accessible through a manager (MCC) account.

        list_accessible_customers() only returns manager-level accounts, not client accounts
        under those managers. We directly query the target customer - if the MCC login_customer_id
        is configured correctly in the client, this will succeed.
        """
        cleaned_customer_id = clean_customer_id(config.customer_id)
        ga_service = client.get_service("GoogleAdsService")
        query = "SELECT customer.id FROM customer"
        try:
            response = ga_service.search(customer_id=cleaned_customer_id, query=query)
            list(response)  # Consume the response to trigger any errors
            return True, None
        except Exception as e:
            error_message = str(e)
            if "CUSTOMER_NOT_FOUND" in error_message or "USER_PERMISSION_DENIED" in error_message:
                return (
                    False,
                    f"Customer ID {config.customer_id} is not accessible. Please verify your customer ID and manager account settings.",
                )
            raise

    def validate_credentials(
        self, config: GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig, team_id: int
    ) -> tuple[bool, str | None]:
        try:
            client = google_ads_client(config, team_id)

            if isinstance(config, GoogleAdsSourceConfig) and config.is_mcc_account and config.is_mcc_account.enabled:
                return self._validate_mcc_customer_access(client, config)

            customer_service = client.get_service("CustomerService")
            accessible_customers = customer_service.list_accessible_customers()

            customer_resource_name = f"customers/{clean_customer_id(config.customer_id)}"
            is_valid = customer_resource_name in accessible_customers.resource_names
            if not is_valid:
                return (
                    False,
                    f"Customer ID {config.customer_id} is not correct. Please check your customer ID and try again.",
                )
            return True, None
        except Exception as e:
            error_message = str(e)
            if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in error_message:
                return (
                    False,
                    "Insufficient permissions. Please reconnect your Google Ads account with the required scopes.",
                )
            if "NOT_ADS_USER" in error_message:
                return (
                    False,
                    "The Google account is not associated with any Google Ads accounts. Please use an account with Google Ads access.",
                )
            return False, f"Error validating credentials: {error_message}"
