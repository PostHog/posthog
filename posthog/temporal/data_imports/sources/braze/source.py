from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.braze.braze import (
    braze_source,
    validate_credentials as validate_braze_credentials,
)
from posthog.temporal.data_imports.sources.braze.settings import ENDPOINTS, INCREMENTAL_FIELDS
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import BrazeSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BrazeSource(SimpleSource[BrazeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BRAZE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BRAZE,
            iconPath="/static/services/braze.png",
            caption="""Connect your Braze account to import campaigns, canvases, segments, events, and analytics data into PostHog Data Warehouse.

You'll need your Braze REST API Key and your Braze REST Endpoint URL. You can find these in your [Braze Dashboard](https://dashboard.braze.com/) under **Settings** → **APIs and Identifiers**.

The REST Endpoint URL typically looks like `https://rest.iad-01.braze.com` - make sure to use the correct endpoint for your Braze instance region.""",
            docsUrl="https://posthog.com/docs/cdp/sources/braze",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="REST API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="your-braze-api-key",
                    ),
                    SourceFieldInputConfig(
                        name="base_url",
                        label="REST endpoint URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://rest.iad-01.braze.com",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="2024-01-01T00:00:00Z",
                    ),
                ],
            ),
            feature_flag="dwh_braze",
        )

    def get_schemas(self, config: BrazeSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

    def validate_credentials(self, config: BrazeSourceConfig, team_id: int) -> tuple[bool, str | None]:
        if not config.base_url.startswith("https://"):
            return False, "Base URL must start with https://"

        if validate_braze_credentials(config.api_key, config.base_url):
            return True, None

        return False, "Invalid Braze credentials"

    def source_for_pipeline(self, config: BrazeSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return braze_source(
            api_key=config.api_key,
            base_url=config.base_url,
            endpoint=inputs.schema_name,
            start_date=config.start_date,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
