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
from posthog.temporal.data_imports.sources.generated_configs import PlainSourceConfig
from posthog.temporal.data_imports.sources.plain.plain import (
    plain_source,
    validate_credentials as validate_plain_credentials,
)
from posthog.temporal.data_imports.sources.plain.settings import ENDPOINTS, INCREMENTAL_FIELDS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PlainSource(SimpleSource[PlainSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLAIN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PLAIN,
            label="Plain",
            releaseStatus="beta",
            featureFlag="dwh_plain",
            caption="""Enter your Plain API key to automatically pull your Plain customer support data into the PostHog Data warehouse.

You can create an API key in your [Plain workspace settings](https://app.plain.com/settings/api-keys).

Make sure to grant the following read permissions:
- customer:read
- thread:read
- timeline:read
""",
            iconPath="/static/services/plain.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="plainApiKey_...",
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Plain credentials. Please check your API key.",
            "403 Client Error": "Access forbidden. Your API key may lack required permissions.",
        }

    def get_schemas(
        self, config: PlainSourceConfig, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PlainSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_plain_credentials(config.api_key)

    def source_for_pipeline(self, config: PlainSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return plain_source(
            api_key=config.api_key,
            endpoint_name=inputs.schema_name,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
