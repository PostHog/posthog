from typing import TYPE_CHECKING, Optional, cast

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
    SuggestedTable,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource, WebhookSource
from posthog.temporal.data_imports.sources.common.mixins import OAuthMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import StripeSourceConfig
from posthog.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
)
from posthog.temporal.data_imports.sources.stripe.settings import (
    ENDPOINTS as STRIPE_ENDPOINTS,
    INCREMENTAL_FIELDS as STRIPE_INCREMENTAL_FIELDS,
)
from posthog.temporal.data_imports.sources.stripe.stripe import (
    StripePermissionError,
    StripeResumeConfig,
    stripe_source,
    validate_credentials as validate_stripe_credentials,
)

from products.data_warehouse.backend.types import ExternalDataSourceType

STRIPE_BASE_URL = "https://dashboard.stripe.com"
STRIPE_ACCOUNT_URL = f"{STRIPE_BASE_URL}/settings/account"

# The API keys URL will pre-fill the form with the account ID, key name and also all the required permissions.
PERMISSIONS = [
    "rak_balance_transaction_source_read",
    "rak_charge_read",
    "rak_customer_read",
    "rak_dispute_read",
    "rak_payout_read",
    "rak_product_read",
    "rak_credit_note_read",
    "rak_invoice_read",
    "rak_plan_read",  # This is `price` in the UI, but `plan` in their API
    "rak_subscription_read",
    "rak_application_fee_read",
    "rak_transfer_read",
    "rak_connected_account_read",
    "rak_payment_method_read",
]
STRIPE_API_KEYS_URL = f"{STRIPE_BASE_URL}/apikeys/create?name=PostHog&{'&'.join([f'permissions[{i}]={permission}' for i, permission in enumerate(PERMISSIONS)])}"


@SourceRegistry.register
class StripeSource(
    ResumableSource[StripeSourceConfig, StripeResumeConfig], WebhookSource[StripeSourceConfig], OAuthMixin
):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STRIPE

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from posthog.temporal.data_imports.sources.stripe.webhook_template import template

        return template

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            caption="Connect your Stripe account to automatically sync your Stripe data into PostHog.",
            iconPath="/static/services/stripe.png",
            docsUrl="https://posthog.com/docs/cdp/sources/stripe",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication type",
                        required=True,
                        defaultValue="oauth",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Connect with Stripe",
                                value="oauth",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldOauthConfig(
                                            name="stripe_integration_id",
                                            label="Stripe account",
                                            required=False,
                                            kind="stripe",
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Restricted API key",
                                value="api_key",
                                deprecated=True,
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="stripe_secret_key",
                                            label="API key",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="rk_live_...",
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="stripe_account_id",
                        label="Account id",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="stripe_account_id",
                    ),
                ],
            ),
            suggestedTables=[
                SuggestedTable(
                    table=CUSTOMER_RESOURCE_NAME,
                    tooltip="Enable for the best Revenue analytics experience.",
                ),
                SuggestedTable(
                    table=CHARGE_RESOURCE_NAME,
                    tooltip="Enable for the best Revenue analytics experience.",
                ),
                SuggestedTable(
                    table=INVOICE_RESOURCE_NAME,
                    tooltip="Enable for the best Revenue analytics experience.",
                ),
                SuggestedTable(
                    table=SUBSCRIPTION_RESOURCE_NAME,
                    tooltip="Enable for the best Revenue analytics experience.",
                ),
                SuggestedTable(
                    table=PRODUCT_RESOURCE_NAME,
                    tooltip="Enable for the best Revenue analytics experience.",
                ),
            ],
            featured=True,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.stripe.com": "Your Stripe credentials do not have permissions to access endpoint. Please check your configuration and permissions in Stripe, then try again.",
            "403 Client Error: Forbidden for url: https://api.stripe.com": "Your Stripe credentials do not have permissions to access endpoint. Please check your configuration and permissions in Stripe, then try again.",
            "Expired API Key provided": "Your Stripe API key has expired. Please create a new key and reconnect.",
            "Invalid API Key provided": None,
            "PermissionError": "Your Stripe credentials do not have permissions to access endpoint. Please check your configuration and permissions in Stripe, then try again.",
        }

    def _get_api_key(self, config: StripeSourceConfig, team_id: int) -> str:
        if config.auth_method.selection == "api_key":
            if not config.auth_method.stripe_secret_key:
                raise ValueError("Missing Stripe API key")
            return config.auth_method.stripe_secret_key

        if not config.auth_method.stripe_integration_id:
            raise ValueError("Missing Stripe integration ID")
        integration = self.get_oauth_integration(config.auth_method.stripe_integration_id, team_id)

        if not integration.access_token:
            raise ValueError("Stripe access token not found")
        return integration.access_token

    def get_schemas(self, config: StripeSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                # nested resources are only full refresh and are not in STRIPE_INCREMENTAL_FIELDS
                supports_append=STRIPE_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=STRIPE_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in STRIPE_ENDPOINTS
        ]

    def validate_credentials(
        self, config: StripeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            api_key = self._get_api_key(config, team_id)
            if validate_stripe_credentials(api_key, schema_name):
                return True, None
            else:
                return False, "Invalid Stripe credentials"
        except StripePermissionError as e:
            missing_resources = ", ".join(e.missing_permissions.keys())
            return False, f"Stripe credentials lack permissions for {missing_resources}"
        except Exception as e:
            return False, str(e)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[StripeResumeConfig]:
        return ResumableSourceManager[StripeResumeConfig](inputs, StripeResumeConfig)

    def source_for_pipeline(
        self,
        config: StripeSourceConfig,
        resumable_source_manager: ResumableSourceManager[StripeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        api_key = self._get_api_key(config, inputs.team_id)

        return stripe_source(
            api_key=api_key,
            account_id=config.stripe_account_id,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
