from posthog.temporal.data_imports.pipelines.doit.source import doit_list_reports, DOIT_INCREMENTAL_FIELDS
from posthog.temporal.data_imports.sources.common.base import BaseSource
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

    def get_schemas(self, config: DoItSourceConfig) -> list[SourceSchema]:
        # TODO: fix the below
        reports = doit_list_reports(doit_config)

        return [
            SourceSchema(
                name=name,
                supports_incremental=True,
                supports_append=True,
                incremental_fields=DOIT_INCREMENTAL_FIELDS,
            )
            for name, _id in reports
        ]

    def validate_credentials(self, config: DoItSourceConfig) -> tuple[bool, str | None]:
        return True, None

    def source_for_pipeline(self, config: DoItSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # TODO: Move the DoIt source func in here
        return SourceResponse(name="", items=iter([]), primary_keys=None)
