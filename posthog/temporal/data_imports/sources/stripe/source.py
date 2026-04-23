from typing import TYPE_CHECKING, Optional, cast

import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.sources.common.webhook_s3 import WAREHOUSE_WEBHOOK_FLAG, WebhookSourceManager

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
from posthog.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
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
from posthog.temporal.data_imports.sources.generated_configs import StripeSourceConfig
from posthog.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    RESOURCE_TO_STRIPE_OBJECT_TYPE,
    SUBSCRIPTION_RESOURCE_NAME,
)
from posthog.temporal.data_imports.sources.stripe.settings import (
    APPEND_ONLY_INCREMENTAL_FIELDS as STRIPE_APPEND_ONLY_INCREMENTAL_FIELDS,
    ENDPOINTS as STRIPE_ENDPOINTS,
)
from posthog.temporal.data_imports.sources.stripe.stripe import (
    StripePermissionError,
    StripeResumeConfig,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
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
    "rak_webhook_write",
]
STRIPE_API_KEYS_URL = f"{STRIPE_BASE_URL}/apikeys/create?name=PostHog&{'&'.join([f'permissions[{i}]={permission}' for i, permission in enumerate(PERMISSIONS)])}"


def _is_webhook_feature_flag_enabled(team_id: int) -> bool:
    from posthog.models import Team

    try:
        team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    except Team.DoesNotExist:
        return False

    try:
        enabled = posthoganalytics.feature_enabled(
            WAREHOUSE_WEBHOOK_FLAG,
            str(team.uuid),
            groups={
                "organization": str(team.organization_id),
                "project": str(team.id),
            },
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id)},
            },
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

        return bool(enabled)
    except Exception as e:
        capture_exception(e)
        return False


@SourceRegistry.register
class StripeSource(
    ResumableSource[StripeSourceConfig, StripeResumeConfig],
    WebhookSource[StripeSourceConfig],
    OAuthMixin,
):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STRIPE

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from posthog.temporal.data_imports.sources.stripe.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return RESOURCE_TO_STRIPE_OBJECT_TYPE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            caption=f"Connect your Stripe account to automatically sync your Stripe data into PostHog. You can choose between OAuth (recommended) or legacy RAK Stripe keys. If you choose the latter, you will need your [Stripe account ID]({STRIPE_ACCOUNT_URL}), and create a [restricted API key]({STRIPE_API_KEYS_URL})",
            permissionsCaption="""Currently, **read permissions are required** for the following resources:
            - Under the **Core** resource type, select *read* for **Balance transaction sources**, **Charges**, **Customers**, **Disputes**, **Payouts**, and **Products**
            - Under the **Billing** resource type, select *read* for **Credit notes**, **Invoices**, **Prices**, and **Subscriptions**
            - Under the **Connect** resource type, select *read* for the **entire resource**
            - Under the **Webhooks** resource type, select *write* for **Webhook endpoints** (required for automatic webhook creation)
            These permissions are automatically pre-filled in the API key creation form if you use the link above, so all you need to do is scroll down and click "Create Key".
            """,
            iconPath="/static/services/stripe.png",
            docsUrl="https://posthog.com/docs/cdp/sources/stripe",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication type",
                        required=True,
                        defaultValue="api_key",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Restricted API key",
                                value="api_key",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="stripe_secret_key",
                                            label="API key",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="rk_live_...",
                                            caption=f"Create a [restricted API key]({STRIPE_API_KEYS_URL}) with the pre-defined permissions",
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="OAuth connection",
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
            webhookSetupCaption="""To set up the webhook manually:

1. Go to your [Stripe Dashboard > Developers > Webhooks](https://dashboard.stripe.com/webhooks)
2. Click **Add endpoint**
3. Paste the webhook URL shown below into the **Endpoint URL** field
4. Under **Events to send**, select **All events** (or choose specific events matching your synced tables)
5. Click **Add endpoint**

Once created, copy the **Signing secret** from the webhook details page and add it to your source configuration for signature verification.

If automatic creation failed due to a permissions error and you're using a restricted API key (not OAuth), your key needs **Write** access on **Webhook endpoints**. You can update this in your [Stripe API keys settings](https://dashboard.stripe.com/apikeys).""",
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="whsec_...",
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.stripe.com": "Your Stripe credentials do not have permissions to access endpoint. Please check your configuration and permissions in Stripe, then try again.",
            "403 Client Error: Forbidden for url: https://api.stripe.com": "Your Stripe credentials do not have permissions to access endpoint. Please check your configuration and permissions in Stripe, then try again.",
            "Expired API Key provided": "Your Stripe API key has expired. Please create a new key and reconnect.",
            "Invalid API Key provided": None,
            "PermissionError": "Your Stripe credentials do not have permissions to access endpoint. Please check your configuration and permissions in Stripe, then try again.",
            # Deterministic credential/config errors from _get_api_key and OAuthMixin
            "Missing Stripe API key": "Stripe API key is not configured. Please update the source configuration.",
            "Missing Stripe integration ID": "Stripe integration ID is not configured. Please reconnect your Stripe account.",
            "Missing integration ID": "Integration ID is not configured. Please reconnect your Stripe account.",
            "Integration not found": "The linked Stripe integration no longer exists. Please reconnect your Stripe account.",
            "Stripe access token not found": "Stripe OAuth access token is missing. Please reconnect your Stripe account.",
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

    def get_schemas(
        self,
        config: StripeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_webhooks=_is_webhook_feature_flag_enabled(team_id)
                and STRIPE_APPEND_ONLY_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                # nested resources are only full refresh and are not in STRIPE_APPEND_ONLY_INCREMENTAL_FIELDS
                supports_append=STRIPE_APPEND_ONLY_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=STRIPE_APPEND_ONLY_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in STRIPE_ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: StripeSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
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

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(self, config: StripeSourceConfig, webhook_url: str, team_id: int) -> WebhookCreationResult:
        api_key = self._get_api_key(config, team_id)
        return create_webhook(api_key, config.stripe_account_id, webhook_url)

    def get_external_webhook_info(
        self, config: StripeSourceConfig, webhook_url: str, team_id: int
    ) -> ExternalWebhookInfo:
        api_key = self._get_api_key(config, team_id)
        return get_external_webhook_info(api_key, config.stripe_account_id, webhook_url)

    def delete_webhook(self, config: StripeSourceConfig, webhook_url: str, team_id: int) -> WebhookDeletionResult:
        api_key = self._get_api_key(config, team_id)
        return delete_webhook(api_key, config.stripe_account_id, webhook_url)

    def source_for_pipeline(
        self,
        config: StripeSourceConfig,
        resumable_source_manager: ResumableSourceManager[StripeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        webhook_source_manager = self.get_webhook_source_manager(inputs)
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
            webhook_source_manager=webhook_source_manager,
        )
