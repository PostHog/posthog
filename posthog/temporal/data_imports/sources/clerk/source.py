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
from posthog.temporal.data_imports.sources.generated_configs import ClerkSourceConfig
from posthog.temporal.data_imports.sources.clerk.settings import (
    ENDPOINTS as CLERK_ENDPOINTS,
    INCREMENTAL_FIELDS as CLERK_INCREMENTAL_FIELDS,
)
from posthog.temporal.data_imports.sources.clerk.clerk import (
    get_clerk_rows,
    validate_clerk_credentials,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ClerkSource(SimpleSource[ClerkSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLERK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLERK,
            caption="""Enter your Clerk secret key to automatically pull your Clerk data into the PostHog data warehouse.

You can find your secret key in your [Clerk Dashboard](https://dashboard.clerk.com/) under **Configure → API Keys**.

**Important:** Make sure to use a secret key (starts with `sk_`), not a publishable key.
""",
            iconPath="/static/services/clerk.png",
            docsUrl="https://posthog.com/docs/cdp/sources/clerk",
            featureFlag="dwh_clerk",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="Secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_live_...",
                    ),
                ],
            ),
        )

    def get_schemas(self, config: ClerkSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=CLERK_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=CLERK_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=CLERK_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in CLERK_ENDPOINTS
        ]

    def validate_credentials(self, config: ClerkSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_clerk_credentials(config.secret_key):
                return True, None
            else:
                return False, "Invalid Clerk credentials"
        except Exception as e:
            return False, str(e)

    def source_for_pipeline(self, config: ClerkSourceConfig, inputs: SourceInputs) -> SourceResponse:
        items = get_clerk_rows(
            api_key=config.secret_key,
            endpoint=inputs.schema_name,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
        )

        return SourceResponse(
            name=inputs.schema_name,
            items=lambda: items,
            primary_keys=["id"],
            partition_mode="datetime",
            partition_format="month",
            partition_keys=["created_at"],
            sort_mode="asc",
        )
