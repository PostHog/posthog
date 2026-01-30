from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    Option,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.customer_io.customerio import (
    customerio_source,
    validate_credentials as validate_customerio_credentials,
)
from posthog.temporal.data_imports.sources.customer_io.settings import ENDPOINTS
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
            label="Customer.io",
            betaSource=True,
            caption="""Enter your Customer.io **App API key** to automatically pull your Customer.io data into the PostHog Data warehouse.

**Important:** You need an **App API key** (not a Track API key or Site ID). You can create one in your [Customer.io Dashboard](https://fly.customer.io/settings/api_credentials) under **API Credentials** → **App API Keys**.

Select the region where your Customer.io account is hosted (US or EU).
""",
            iconPath="/static/services/customer-io.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="App API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Enter your App API key",
                    ),
                    SourceFieldSelectConfig(
                        name="api_region",
                        label="Region",
                        required=True,
                        options=[
                            Option(label="US", value="US"),
                            Option(label="EU", value="EU"),
                        ],
                        defaultValue="US",
                    ),
                ],
            ),
        )

    def get_schemas(
        self, config: CustomerIOSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        # Customer.io only supports full refresh - the API doesn't support filtering by updated_at
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in list(ENDPOINTS)
        ]

    def validate_credentials(
        self, config: CustomerIOSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_customerio_credentials(config.api_key, config.api_region)

    def source_for_pipeline(self, config: CustomerIOSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return customerio_source(
            api_key=config.api_key,
            region=config.api_region,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )
