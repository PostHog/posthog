from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.common.utils import dlt_source_to_source_response
from posthog.temporal.data_imports.sources.generated_configs import KlaviyoSourceConfig
from posthog.temporal.data_imports.sources.klaviyo.klaviyo import (
    klaviyo_source,
    validate_credentials as validate_klaviyo_credentials,
)
from posthog.temporal.data_imports.sources.klaviyo.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KlaviyoSource(SimpleSource[KlaviyoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KLAVIYO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KLAVIYO,
            label="Klaviyo",
            caption="""Enter your Klaviyo API key to automatically pull your Klaviyo data into the PostHog Data warehouse.

You can create a private API key in your [Klaviyo account settings](https://www.klaviyo.com/settings/account/api-keys).

Make sure to grant the following read permissions:
- Campaigns
- Events
- Flows
- Lists
- Metrics
- Profiles
""",
            iconPath="/static/services/klaviyo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/klaviyo",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pk_...",
                    ),
                ],
            ),
            featureFlag="dwh_klaviyo",
        )

    def get_schemas(self, config: KlaviyoSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

    def validate_credentials(self, config: KlaviyoSourceConfig, team_id: int) -> tuple[bool, str | None]:
        if validate_klaviyo_credentials(config.api_key):
            return True, None

        return False, "Invalid Klaviyo API key"

    def source_for_pipeline(self, config: KlaviyoSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return dlt_source_to_source_response(
            klaviyo_source(
                api_key=config.api_key,
                endpoint=inputs.schema_name,
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                should_use_incremental_field=inputs.should_use_incremental_field,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value
                if inputs.should_use_incremental_field
                else None,
            )
        )
