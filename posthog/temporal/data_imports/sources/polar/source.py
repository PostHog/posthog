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
from posthog.temporal.data_imports.sources.generated_configs import PolarSourceConfig
from posthog.temporal.data_imports.sources.polar.polar import polar_source, validate_credentials
from posthog.temporal.data_imports.sources.polar.settings import (
    ENDPOINTS as POLAR_ENDPOINTS,
    INCREMENTAL_FIELDS,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PolarSource(SimpleSource[PolarSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POLAR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.POLAR,
            label="Polar",
            caption="""Connect your Polar account to automatically import orders, subscriptions, customers, and more into the PostHog Data warehouse.

You'll need an **Organization Access Token** from your Polar dashboard. To create one:

1. Go to your [Polar Settings](https://polar.sh/settings)
2. Navigate to Access Tokens
3. Create a new Organization Access Token with read permissions

Optionally, you can filter data by Organization ID if you manage multiple organizations.
""",
            iconPath="/static/services/polar.png",
            docsUrl="https://docs.polar.sh/api-reference/introduction",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Organization Access Token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="polar_oat_...",
                    ),
                    SourceFieldInputConfig(
                        name="organization_id",
                        label="Organization ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Filter by specific organization",
                    ),
                ],
            ),
            feature_flag="dwh_polar",
        )

    def validate_credentials(self, config: PolarSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_credentials(config.access_token):
                return True, None
            else:
                return False, "Invalid Polar access token"
        except Exception as e:
            return False, str(e)

    def get_schemas(self, config: PolarSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=True,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in POLAR_ENDPOINTS
        ]

    def source_for_pipeline(self, config: PolarSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return polar_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            organization_id=config.organization_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            logger=inputs.logger,
        )
