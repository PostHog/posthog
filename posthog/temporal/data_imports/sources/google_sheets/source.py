from typing import cast

import gspread

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import GoogleSheetsSourceConfig
from posthog.temporal.data_imports.sources.google_sheets.google_sheets import (
    get_schema_incremental_fields as get_google_sheets_schema_incremental_fields,
    get_schemas as get_google_sheets_schemas,
    google_sheets_client,
    google_sheets_source,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleSheetsSource(BaseSource[GoogleSheetsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLESHEETS

    def get_schemas(
        self, config: GoogleSheetsSourceConfig, team_id: int, with_counts: bool = False
    ) -> list[SourceSchema]:
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

    def source_for_pipeline(self, config: GoogleSheetsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return google_sheets_source(
            config,
            inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    def validate_credentials(self, config: GoogleSheetsSourceConfig, team_id: int) -> tuple[bool, str | None]:
        client = google_sheets_client()
        try:
            client.open_by_url(config.spreadsheet_url)
            return True, None
        except gspread.SpreadsheetNotFound:
            return False, "Spreadsheet not found at URL provided"
        except PermissionError:
            return (
                False,
                "Permissions missing from spreadsheet. View documentation at https://posthog.com/docs/cdp/sources/google-sheets",
            )
        except Exception as e:
            return False, str(e)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_SHEETS,
            label="Google Sheets",
            caption="Ensure you have granted PostHog access to your Google Sheet as instructed in the [documentation](https://posthog.com/docs/cdp/sources/google-sheets)",
            betaSource=True,
            iconPath="/static/services/Google_Sheets.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/google-sheets",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="spreadsheet_url",
                        label="Spreadsheet URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                    )
                ],
            ),
        )
