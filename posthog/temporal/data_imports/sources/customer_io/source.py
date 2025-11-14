from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectOption,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.common.utils import dlt_source_to_source_response
from posthog.temporal.data_imports.sources.customer_io.customer_io import (
    customer_io_source,
    validate_credentials as validate_customer_io_credentials,
)
from posthog.temporal.data_imports.sources.customer_io.settings import ENDPOINTS, INCREMENTAL_FIELDS
from posthog.temporal.data_imports.sources.generated_configs import CustomerIOSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CustomerIOSource(SimpleSource[CustomerIOSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CUSTOMERIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CUSTOMER_IO,
            iconPath="/static/services/customerio.png",
            label="Customer.io",
            caption="""Enter your Customer.io App API credentials to automatically pull your Customer.io data into the PostHog Data warehouse.

You can find your App API Key in the [Customer.io App API Keys section](https://fly.customer.io/settings/api_credentials). Make sure you're using an **App API Key**, not a Tracking API key.

The Customer.io connector supports importing data from the following resources:
- Campaigns
- Newsletters
- Messages
- Actions
- Segments
- Broadcasts
""",
            docsUrl="https://posthog.com/docs/cdp/sources/customer-io",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="app_api_key",
                        label="App API Key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Enter your Customer.io App API Key",
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        options=[
                            SourceFieldSelectOption(label="United States", value="US"),
                            SourceFieldSelectOption(label="European Union", value="EU"),
                        ],
                        defaultValue="US",
                    ),
                ],
            ),
            feature_flag="dwh_customerio",
        )

    def validate_credentials(self, config: CustomerIOSourceConfig, team_id: int) -> tuple[bool, str | None]:
        if validate_customer_io_credentials(config.app_api_key, config.region):
            return True, None

        return False, "Invalid Customer.io App API credentials"

    def get_schemas(
        self, config: CustomerIOSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

    def source_for_pipeline(self, config: CustomerIOSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return dlt_source_to_source_response(
            customer_io_source(
                app_api_key=config.app_api_key,
                region=config.region,
                endpoint=inputs.schema_name,
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                should_use_incremental_field=inputs.should_use_incremental_field,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value
                if inputs.should_use_incremental_field
                else None,
            )
        )
