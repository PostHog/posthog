from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import ResumableSourceResponse, SourceInputs
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource, ResumableSourceManager
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import StripeSourceConfig
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


@SourceRegistry.register
class StripeSource(ResumableSource[StripeSourceConfig, StripeResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STRIPE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            caption="""Enter your Stripe credentials to automatically pull your Stripe data into the PostHog Data warehouse.

You can find your account ID [in your Stripe dashboard](https://dashboard.stripe.com/settings/account), and create a secret key [here](https://dashboard.stripe.com/apikeys/create).

Currently, **read permissions are required** for the following resources:

- Under the **Core** resource type, select *read* for **Balance transaction sources**, **Charges**, **Customers**, **Disputes**, **Payouts**, and **Products**
- Under the **Billing** resource type, select *read* for **Credit notes**, **Invoices**, **Prices**, and **Subscriptions**
- Under the **Connect** resource type, select *read* for either the **entire resource** or **Application Fees** and **Transfers**

You can also simplify the setup by selecting **read** for the **entire resource** under **Core**, **Billing**, and **Connect**.
""",
            iconPath="/static/services/stripe.png",
            docsUrl="https://posthog.com/docs/cdp/sources/stripe",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="stripe_account_id",
                        label="Account id",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="stripe_account_id",
                    ),
                    SourceFieldInputConfig(
                        name="stripe_secret_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="rk_live_...",
                    ),
                ],
            ),
        )

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

    def validate_credentials(self, config: StripeSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_stripe_credentials(config.stripe_secret_key):
                return True, None
            else:
                return False, "Invalid Stripe credentials"
        except StripePermissionError as e:
            missing_resources = ", ".join(e.missing_permissions.keys())
            return False, f"Stripe API key lacks permissions for {missing_resources}"
        except Exception as e:
            return False, str(e)

    def source_for_pipeline(
        self,
        config: StripeSourceConfig,
        resumable_source_manager: ResumableSourceManager[StripeResumeConfig],
        inputs: SourceInputs,
    ) -> ResumableSourceResponse:
        return stripe_source(
            api_key=config.stripe_secret_key,
            account_id=config.stripe_account_id,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value,
            logger=inputs.logger,
        )
