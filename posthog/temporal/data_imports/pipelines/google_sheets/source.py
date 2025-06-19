from dlt.common.normalizers.naming.snake_case import NamingConvention
from google.oauth2 import service_account
import gspread
from posthog.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from posthog.temporal.data_imports.pipelines.source import config
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse


@config.config
class GoogleSheetsServiceAccountSourceConfig(config.Config):
    """Google Sheets source config using service account for authentication."""

    spreadsheet_url: str

    private_key: str = config.value(
        default_factory=config.default_from_settings("GOOGLE_SHEETS_SERVICE_ACCOUNT_PRIVATE_KEY")
    )
    private_key_id: str = config.value(
        default_factory=config.default_from_settings("GOOGLE_SHEETS_SERVICE_ACCOUNT_PRIVATE_KEY_ID")
    )
    client_email: str = config.value(
        default_factory=config.default_from_settings("GOOGLE_SHEETS_SERVICE_ACCOUNT_CLIENT_EMAIL")
    )
    token_uri: str = config.value(
        default_factory=config.default_from_settings("GOOGLE_SHEETS_SERVICE_ACCOUNT_TOKEN_URI")
    )


def google_sheets_client(
    config: GoogleSheetsServiceAccountSourceConfig,
) -> gspread.Client:
    credentials = service_account.Credentials.from_service_account_info(
        {
            "private_key": config.private_key,
            "private_key_id": config.private_key_id,
            "token_uri": config.token_uri,
            "client_email": config.client_email,
        },
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
    )
    return gspread.authorize(credentials)


def get_schemas(config: GoogleSheetsServiceAccountSourceConfig) -> list[tuple[str, int]]:
    """Returns a tuple of worksheets in the form of (title, id)"""

    client = google_sheets_client(config)
    spreadsheet = client.open_by_url(config.spreadsheet_url)
    worksheets = spreadsheet.worksheets()

    return [(NamingConvention().normalize_identifier(worksheet.title), worksheet.id) for worksheet in worksheets]


def google_sheets_source(config: GoogleSheetsServiceAccountSourceConfig, worksheet_name: str) -> SourceResponse:
    worksheets = get_schemas(config)
    selected_worksheet = [id for name, id in worksheets if name == worksheet_name]
    if len(selected_worksheet) == 0:
        raise Exception(f'Worksheet titled "{worksheet_name}" can\'t be found')

    worksheet_id = selected_worksheet[0]

    client = google_sheets_client(config)
    spreadsheet = client.open_by_url(config.spreadsheet_url)
    worksheet = spreadsheet.get_worksheet_by_id(worksheet_id)

    headers = worksheet.get_all_values("1:1")  # Get the first row
    primary_keys = None
    if len(headers) > 0 and "id" in headers[0]:
        primary_keys = ["id"]

    def get_rows():
        client = google_sheets_client(config)
        spreadsheet = client.open_by_url(config.spreadsheet_url)

        worksheet = spreadsheet.get_worksheet_by_id(worksheet_id)

        values = worksheet.get_all_records()

        yield table_from_py_list(values)

    return SourceResponse(name=worksheet_name, items=get_rows(), primary_keys=primary_keys)
