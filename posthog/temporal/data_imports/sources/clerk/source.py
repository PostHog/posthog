from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.clerk.clerk import (
    clerk_source,
    validate_credentials as validate_clerk_credentials,
)
from posthog.temporal.data_imports.sources.clerk.settings import ENDPOINTS
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import ClerkSourceConfig

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
            label="Clerk",
            betaSource=True,
            caption="""Enter your Clerk secret key to automatically pull your Clerk data into the PostHog Data warehouse.

You can find your secret key in your [Clerk Dashboard](https://dashboard.clerk.com/) under **API Keys**.

The secret key starts with `sk_live_`.
""",
            iconPath="/static/services/clerk.png",
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
        # Clerk only supports full refresh - the API doesn't support filtering by updated_at
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
        self, config: ClerkSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_clerk_credentials(config.secret_key)

    def source_for_pipeline(self, config: ClerkSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return clerk_source(
            secret_key=config.secret_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )
