from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import RipplingSourceConfig
from posthog.temporal.data_imports.sources.rippling.rippling import (
    RipplingResumeConfig,
    rippling_source,
    validate_credentials as validate_rippling_credentials,
)
from posthog.temporal.data_imports.sources.rippling.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RipplingSource(ResumableSource[RipplingSourceConfig, RipplingResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RIPPLING

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://rest.ripplingapis.com": "Rippling authentication failed. Please check your API token (tokens expire after 30 days of inactivity).",
            "403 Client Error: Forbidden for url: https://rest.ripplingapis.com": "Rippling denied access. Please check that your API token has the read scope enabled for this dataset.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RIPPLING,
            label="Rippling",
            caption="""Enter your Rippling API token to pull your Rippling workforce data into the PostHog Data warehouse.

A Rippling admin can create a scoped API token under Settings > Company Settings > API Access. Enable the read scope for each dataset you want to sync (e.g. `companies.read`, `users.read`, `workers.read`, `departments.read`, `teams.read`, `levels.read`, `work-locations.read`, `employment-types.read`, `compensations.read`). Note that tokens expire after 30 days of inactivity.""",
            iconPath="/static/services/rippling.png",
            docsUrl="https://posthog.com/docs/cdp/sources/rippling",
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
        config: RipplingSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: RipplingSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_rippling_credentials(config.api_token):
            return True, None

        return False, "Invalid Rippling API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RipplingResumeConfig]:
        return ResumableSourceManager[RipplingResumeConfig](inputs, RipplingResumeConfig)

    def source_for_pipeline(
        self,
        config: RipplingSourceConfig,
        resumable_source_manager: ResumableSourceManager[RipplingResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return rippling_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
