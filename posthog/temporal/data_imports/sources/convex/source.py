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
from posthog.temporal.data_imports.sources.convex.convex import (
    convex_source,
    get_json_schemas,
    validate_credentials as validate_convex_credentials,
)
from posthog.temporal.data_imports.sources.generated_configs import ConvexSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalField, IncrementalFieldType


@SourceRegistry.register
class ConvexSource(SimpleSource[ConvexSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONVEX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CONVEX,
            label="Convex",
            betaSource=True,
            caption="""Enter your Convex deployment URL and deploy key to sync your Convex tables into PostHog.

You can find your deployment URL and deploy key in your [Convex Dashboard](https://dashboard.convex.dev/) under **Settings** > **URL & Deploy Key**.

**Note:** This integration requires the [Convex Professional plan](https://www.convex.dev/plans) for streaming export access.
""",
            iconPath="/static/services/convex.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="deploy_url",
                        label="Deployment URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://your-deployment-123.convex.cloud",
                    ),
                    SourceFieldInputConfig(
                        name="deploy_key",
                        label="Deploy key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="prod:...",
                    ),
                ],
            ),
        )

    def get_schemas(self, config: ConvexSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        schemas_response = get_json_schemas(config.deploy_url, config.deploy_key)

        tables: list[str] = []
        if isinstance(schemas_response, dict):
            tables = list(schemas_response.keys())

        incremental_field: list[IncrementalField] = [
            IncrementalField(
                label="_ts",
                type=IncrementalFieldType.Integer,
                field="_ts",
                field_type=IncrementalFieldType.Integer,
            )
        ]

        return [
            SourceSchema(
                name=table_name,
                supports_incremental=True,
                supports_append=True,
                incremental_fields=incremental_field,
            )
            for table_name in tables
        ]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Authentication failed. Check your Convex deploy key.",
            "403 Client Error": "Access denied. Check your Convex deploy key.",
            "StreamingExportNotEnabled": "Streaming export requires the Convex Professional plan. See https://www.convex.dev/plans to upgrade.",
        }

    def validate_credentials(
        self, config: ConvexSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_convex_credentials(config.deploy_url, config.deploy_key)

    def source_for_pipeline(self, config: ConvexSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return convex_source(
            deploy_url=config.deploy_url,
            deploy_key=config.deploy_key,
            table_name=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )
