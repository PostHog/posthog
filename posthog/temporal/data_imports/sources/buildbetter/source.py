from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.buildbetter.buildbetter import (
    buildbetter_source,
    validate_credentials as validate_buildbetter_credentials,
)
from posthog.temporal.data_imports.sources.buildbetter.settings import ENDPOINTS, INCREMENTAL_FIELDS
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import BuildBetterSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BuildBetterSource(SimpleSource[BuildBetterSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BUILDBETTER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "BuildBetter authentication failed. Please check your API key.",
            "403 Client Error": "BuildBetter access forbidden. Please check your API key permissions.",
        }

    def get_schemas(
        self, config: BuildBetterSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

    def validate_credentials(
        self, config: BuildBetterSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_buildbetter_credentials(config.api_key)

    def source_for_pipeline(self, config: BuildBetterSourceConfig, inputs: SourceInputs) -> SourceResponse:
        incremental_field_last_value = None
        if inputs.should_use_incremental_field and inputs.db_incremental_field_last_value is not None:
            incremental_field_last_value = str(inputs.db_incremental_field_last_value)

        return buildbetter_source(
            api_key=config.api_key,
            endpoint_name=inputs.schema_name,
            logger=inputs.logger,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_last_value=incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BUILD_BETTER,
            label="BuildBetter",
            betaSource=True,
            caption="Connect your BuildBetter workspace to sync interviews, extractions, and documents.",
            iconPath="/static/services/buildbetter.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                    ),
                ],
            ),
        )
