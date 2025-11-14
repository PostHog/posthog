from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.customer_io.client import (
    CustomerIOAPIError,
    CustomerIOPermissionError,
    customerio_source,
    validate_credentials as validate_customerio_credentials,
)
from posthog.temporal.data_imports.sources.customer_io.settings import (
    ENDPOINTS as CUSTOMERIO_ENDPOINTS,
    INCREMENTAL_FIELDS as CUSTOMERIO_INCREMENTAL_FIELDS,
)
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
            iconPath="/static/services/customer-io.png",
            label="Customer.io",
            caption="""Enter your Customer.io credentials to automatically pull your Customer.io data into the PostHog data warehouse.

You can generate an App API Key in your [Customer.io account settings](https://fly.customer.io/settings/api_credentials).

**Required permissions:** The API key must have read access to campaigns, newsletters, and activities.
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
                        placeholder="Bearer token from Customer.io",
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="United States (US)",
                                value="us",
                            ),
                            SourceFieldSelectConfigOption(
                                label="European Union (EU)",
                                value="eu",
                            ),
                        ],
                    ),
                ],
            ),
            featureFlag="dwh_customerio",
        )

    def validate_credentials(self, config: CustomerIOSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_customerio_credentials(config.app_api_key, config.region):
                return True, None
            else:
                return False, "Invalid Customer.io credentials"
        except CustomerIOPermissionError as e:
            return False, f"Customer.io API key lacks required permissions: {str(e)}"
        except CustomerIOAPIError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Unexpected error validating credentials: {str(e)}"

    def get_schemas(
        self, config: CustomerIOSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=True,
                supports_append=CUSTOMERIO_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=CUSTOMERIO_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in CUSTOMERIO_ENDPOINTS
        ]

    def source_for_pipeline(self, config: CustomerIOSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return customerio_source(
            app_api_key=config.app_api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            logger=inputs.logger,
        )
