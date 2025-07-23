from typing import cast
from posthog.schema import (
    ExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    Type4,
)
from posthog.temporal.data_imports.pipelines.doit.source import doit_source, doit_list_reports, DOIT_INCREMENTAL_FIELDS
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import DoItSourceConfig
from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class DoItSource(BaseSource[DoItSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.DOIT

    def get_schemas(self, config: DoItSourceConfig, team_id: int) -> list[SourceSchema]:
        reports = doit_list_reports(config)

        return [
            SourceSchema(
                name=name,
                supports_incremental=True,
                supports_append=True,
                incremental_fields=DOIT_INCREMENTAL_FIELDS,
            )
            for name, _id in reports
        ]

    def source_for_pipeline(self, config: DoItSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return doit_source(
            config,
            inputs.schema_name,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DO_IT,
            label="DoIt",
            caption="",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key", label="API key", type=Type4.TEXT, required=True, placeholder=""
                    )
                ],
            ),
        )
