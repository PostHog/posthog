from typing import cast
from posthog.schema import ExternalDataSourceType, SourceConfig, SourceFieldInputConfig, Type4
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema

from posthog.temporal.data_imports.pipelines.stripe import (
    StripePermissionError,
    stripe_source,
    validate_credentials as validate_stripe_credentials,
)
from posthog.temporal.data_imports.pipelines.stripe.settings import (
    ENDPOINTS as STRIPE_ENDPOINTS,
    INCREMENTAL_FIELDS as STRIPE_INCREMENTAL_FIELDS,
)
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import StripeSourceConfig
from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class StripeSource(BaseSource[StripeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.STRIPE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.STRIPE,
            caption="""Enter your Stripe credentials to automatically pull your Stripe data into the PostHog Data warehouse.

You can find your account ID [in your Stripe dashboard](https://dashboard.stripe.com/settings/account), and create a secret key [here](https://dashboard.stripe.com/apikeys/create).

Currently, **read permissions are required** for the following resources:

- Under the **Core** resource type, select *read* for **Balance transaction sources**, **Charges**, **Customer**, **Product**, **Disputes**, and **Payouts**
- Under the **Billing** resource type, select *read* for **Invoice**, **Price**, **Subscription**, and **Credit notes**
- Under the **Connected** resource type, select *read* for the **entire resource**""",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="stripe_account_id",
                        label="Account id",
                        type=Type4.TEXT,
                        required=False,
                        placeholder="stripe_account_id",
                    ),
                    SourceFieldInputConfig(
                        name="stripe_secret_key",
                        label="API key",
                        type=Type4.PASSWORD,
                        required=True,
                        placeholder="rk_live_...",
                    ),
                ],
            ),
        )

    def get_schemas(self, config: StripeSourceConfig, team_id: int) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=True,
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

    def source_for_pipeline(self, config: StripeSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return stripe_source(
            api_key=config.stripe_secret_key,
            account_id=config.stripe_account_id,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value,
            logger=inputs.logger,
        )
