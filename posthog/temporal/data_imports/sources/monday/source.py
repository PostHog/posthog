from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import MondaySourceConfig
from posthog.temporal.data_imports.sources.monday.monday import (
    monday_source,
    validate_credentials as validate_monday_credentials,
)
from posthog.temporal.data_imports.sources.monday.settings import ENDPOINTS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MondaySource(SimpleSource[MondaySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MONDAY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Scope GraphQL matches to auth/permission failures only — a broad "monday.com GraphQL error"
        # key would also catch transient server-side errors and permanently disable the sync.
        return {
            "401 Client Error: Unauthorized for url: https://api.monday.com": "monday.com authentication failed. Please check your API token.",
            "monday.com GraphQL error: Not authenticated": "monday.com authentication failed. Please check your API token.",
            "monday.com GraphQL error: User unauthorized": "monday.com rejected the request. Please check that your API token has access to the requested data.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MONDAY,
            label="monday.com",
            caption="""Enter your monday.com API token to pull your boards and items into the PostHog Data warehouse.

You can find your personal API token in monday.com under your avatar > Developers > My access tokens (admins can also use the account API token). Items are synced from every board the token can access.""",
            iconPath="/static/services/monday.png",
            docsUrl="https://posthog.com/docs/cdp/sources/monday",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: MondaySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # GraphQL list queries have no honest updated-since filter (incremental
        # would need the plan-limited activity log), so full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: MondaySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_monday_credentials(config.api_token):
            return True, None

        return False, "Invalid monday.com API token"

    def source_for_pipeline(self, config: MondaySourceConfig, inputs: SourceInputs) -> SourceResponse:
        return monday_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
