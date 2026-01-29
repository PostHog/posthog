from typing import Optional, cast

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
from posthog.temporal.data_imports.sources.polar.polar import (
    polar_source,
    validate_credentials as validate_polar_credentials,
)
from posthog.temporal.data_imports.sources.polar.settings import ENDPOINTS, INCREMENTAL_FIELDS

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
            betaSource=True,
            caption="""Enter your Polar API key to automatically pull your Polar data into the PostHog Data warehouse.

You can create an Organization Access Token in your [Polar organization settings](https://polar.sh/dashboard).

Go to Settings > Developers > Organization Access Tokens and create a new token with read permissions for:
- Customers
- Products
- Orders
- Subscriptions
- Events
""",
            iconPath="/static/services/polar.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="polar_oat_...",
                    ),
                ],
            ),
        )

    def get_schemas(self, config: PolarSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        # Events are immutable - append-only is the only sync mode
        append_only_endpoints = {"events"}

        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None
                and endpoint not in append_only_endpoints,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

    def validate_credentials(
        self, config: PolarSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_polar_credentials(config.api_key):
            return True, None

        return False, "Invalid Polar API key"

    def source_for_pipeline(self, config: PolarSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return polar_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
