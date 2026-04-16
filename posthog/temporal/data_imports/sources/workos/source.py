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
from posthog.temporal.data_imports.sources.generated_configs import WorkOSSourceConfig
from posthog.temporal.data_imports.sources.workos.settings import ENDPOINTS
from posthog.temporal.data_imports.sources.workos.workos import (
    validate_credentials as validate_workos_credentials,
    workos_source,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WorkOSSource(SimpleSource[WorkOSSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WORKOS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WORK_OS,
            iconPath="/static/services/workos.png",
            label="WorkOS",
            caption="""Enter your WorkOS API key to automatically pull your WorkOS data into the PostHog Data warehouse.

You can find your api key in your [WorkOS Dashboard](https://dashboard.workos.com/) under **API Keys**.

The api key starts with `sk_`.
""",
            docsUrl=None,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_...",
                    ),
                ],
            ),
        )

    def validate_credentials(
        self, config: WorkOSSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_workos_credentials(config.api_key)

    def get_schemas(
        self, config: WorkOSSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        # WorkOS only supports full refresh - the API doesn't support filtering by updated_at
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

    def source_for_pipeline(self, config: WorkOSSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return workos_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )
