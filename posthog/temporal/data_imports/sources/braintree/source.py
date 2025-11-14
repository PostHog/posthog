from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.braintree.braintree import (
    braintree_source,
    validate_credentials as validate_braintree_credentials,
)
from posthog.temporal.data_imports.sources.braintree.settings import ENDPOINTS, INCREMENTAL_FIELDS
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import BraintreeSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BraintreeSource(SimpleSource[BraintreeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BRAINTREE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BRAINTREE,
            caption="""Enter your Braintree credentials to automatically pull your Braintree payment data into the PostHog Data warehouse.

You can find your credentials in your [Braintree Control Panel](https://www.braintreegateway.com/login) under Settings → API Keys.

**Required Credentials:**
- **Merchant ID**: Your unique merchant identifier
- **Public Key**: Your API public key
- **Private Key**: Your API private key
- **Environment**: Choose between Production and Sandbox

Make sure your API keys have the necessary permissions to read payment data from Braintree.
""",
            iconPath="/static/services/braintree.png",
            docsUrl="https://posthog.com/docs/cdp/sources/braintree",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="merchant_id",
                        label="Merchant ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your_merchant_id",
                    ),
                    SourceFieldInputConfig(
                        name="public_key",
                        label="Public key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your_public_key",
                    ),
                    SourceFieldInputConfig(
                        name="private_key",
                        label="Private key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="your_private_key",
                    ),
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            {"label": "Production", "value": "production"},
                            {"label": "Sandbox", "value": "sandbox"},
                        ],
                    ),
                ],
            ),
            featureFlag="dwh_braintree",
        )

    def get_schemas(self, config: BraintreeSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

    def validate_credentials(self, config: BraintreeSourceConfig, team_id: int) -> tuple[bool, str | None]:
        if validate_braintree_credentials(
            config.merchant_id,
            config.public_key,
            config.private_key,
            config.environment,
        ):
            return True, None

        return False, "Invalid Braintree credentials"

    def source_for_pipeline(self, config: BraintreeSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return braintree_source(
            merchant_id=config.merchant_id,
            public_key=config.public_key,
            private_key=config.private_key,
            environment=config.environment,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value,
        )
