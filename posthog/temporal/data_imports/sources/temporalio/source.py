from posthog.temporal.data_imports.sources.common.base import BaseSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.pipelines.temporalio.source import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    temporalio_source,
    TemporalIOResource,
)
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import TemporalIOSourceConfig
from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class TemporalIOSource(BaseSource[TemporalIOSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.TEMPORALIO

    def get_schemas(self, config: TemporalIOSourceConfig, team_id: int) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

    def source_for_pipeline(self, config: TemporalIOSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return temporalio_source(
            config,
            TemporalIOResource(inputs.schema_name),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
