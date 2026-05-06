from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.clerk.clerk import (
    ClerkResumeConfig,
    clerk_source,
    validate_credentials as validate_clerk_credentials,
)
from posthog.temporal.data_imports.sources.clerk.settings import ENDPOINTS
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import ClerkSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ClerkSource(ResumableSource[ClerkSourceConfig, ClerkResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLERK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLERK,
            label="Clerk",
            releaseStatus="beta",
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
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self, config: ClerkSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        # Clerk only supports full refresh - the API doesn't support filtering by updated_at
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in list(ENDPOINTS)
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.clerk.com": "Your Clerk secret key is invalid or has been revoked. Please update the secret key in your Clerk dashboard and reconnect.",
            "403 Client Error: Forbidden for url: https://api.clerk.com": "Your Clerk secret key does not have permission to access this endpoint. Please check the key's permissions in your Clerk dashboard.",
        }

    def validate_credentials(
        self, config: ClerkSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_clerk_credentials(config.secret_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ClerkResumeConfig]:
        return ResumableSourceManager[ClerkResumeConfig](inputs, ClerkResumeConfig)

    def source_for_pipeline(
        self,
        config: ClerkSourceConfig,
        resumable_source_manager: ResumableSourceManager[ClerkResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return clerk_source(
            secret_key=config.secret_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
