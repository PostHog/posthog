from posthog.temporal.data_imports.pipelines.google_sheets.source import (
    get_schemas as get_google_sheets_schemas,
    get_schema_incremental_fields as get_google_sheets_schema_incremental_fields,
)
from posthog.temporal.data_imports.sources.common.base import BaseSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import GoogleSheetsSourceConfig
from posthog.warehouse.models import ExternalDataSource


@SourceRegistry.register
class GoogleSheetsSource(BaseSource[GoogleSheetsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSource.Type:
        return ExternalDataSource.Type.GOOGLESHEETS

    def get_schemas(self, config: GoogleSheetsSourceConfig) -> list[SourceSchema]:
        # TODO: fix the below
        sheets = get_google_sheets_schemas(config)

        schemas: list[SourceSchema] = []
        for name, _ in sheets:
            incremental_fields = get_google_sheets_schema_incremental_fields(config, name)

            schemas.append(
                SourceSchema(
                    name=name,
                    supports_incremental=len(incremental_fields) > 0,
                    supports_append=len(incremental_fields) > 0,
                    incremental_fields=incremental_fields,
                )
            )

        return schemas

    def validate_credentials(self, config: GoogleSheetsSourceConfig) -> tuple[bool, str | None]:
        return True, None

    def source_for_pipeline(self, config: GoogleSheetsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # TODO: Move the Google Sheets source func in here
        return SourceResponse(name="", items=iter([]), primary_keys=None)
