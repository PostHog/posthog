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
from posthog.temporal.data_imports.sources.generated_configs import ConvexSourceConfig
from posthog.temporal.data_imports.sources.convex.convex import (
    convex_source,
    get_convex_schemas,
    validate_convex_credentials,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ConvexSource(SimpleSource[ConvexSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONVEX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CONVEX,
            caption="""Enter your Convex deployment details to automatically pull your Convex data into the PostHog Data warehouse.

You can find your deployment URL in the Settings tab of your [Convex dashboard](https://dashboard.convex.dev/).

To create a deploy key, navigate to the Settings tab in your Convex dashboard and click "Generate a deploy key". Make sure to copy the key immediately as it won't be shown again.

**Note:** Only Professional plan Convex projects support data export. The deploy key provides full read and write access to your Convex data, so store it securely.
""",
            iconPath="/static/services/convex.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/convex",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="deployment_url",
                        label="Deployment URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://your-deployment.convex.cloud",
                    ),
                    SourceFieldInputConfig(
                        name="access_key",
                        label="Deploy key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="prod:...",
                    ),
                ],
            ),
            feature_flag="dwh_convex",
        )

    def get_schemas(
        self, config: ConvexSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        return get_convex_schemas(config.deployment_url, config.access_key)

    def validate_credentials(self, config: ConvexSourceConfig, team_id: int) -> tuple[bool, str | None]:
        try:
            if validate_convex_credentials(config.deployment_url, config.access_key):
                return True, None
            else:
                return False, "Invalid Convex credentials"
        except Exception as e:
            return False, str(e)

    def source_for_pipeline(self, config: ConvexSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return convex_source(
            deployment_url=config.deployment_url,
            access_key=config.access_key,
            table_name=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            logger=inputs.logger,
        )
