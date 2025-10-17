import time
import random
from typing import Any, Optional

from django.conf import settings

import gspread
from cachetools import Cache, TTLCache, cached
from dlt.common.normalizers.naming.snake_case import NamingConvention
from google.oauth2 import service_account

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from posthog.temporal.data_imports.sources.generated_configs import GoogleSheetsSourceConfig
from posthog.warehouse.types import IncrementalField, IncrementalFieldType


def google_sheets_client() -> gspread.Client:
    credentials = service_account.Credentials.from_service_account_info(
        {
            "private_key": settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_PRIVATE_KEY,
            "private_key_id": settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_PRIVATE_KEY_ID,
            "token_uri": settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_TOKEN_URI,
            "client_email": settings.GOOGLE_SHEETS_SERVICE_ACCOUNT_CLIENT_EMAIL,
        },
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"],
    )
    return gspread.authorize(credentials)


cache: Cache[Any, Any] = TTLCache(maxsize=500, ttl=120)  # 120 seconds
max_attempts = 10
jitter_in_seconds = 10
sleep_per_attempt_in_seconds = 30


@cached(cache)
def _get_worksheet(spreadsheet_url: str, worksheet_id: int) -> gspread.Worksheet:
    """Attempt to get a worksheet with linear backoff. Google Sheets has a 300
    request quota per minute. We add a +- 10s jitter to the sleep per attempt so
    that multiple jobs blocked by quota limits dont all retry at the same time"""

    def execute():
        client = google_sheets_client()
        spreadsheet = client.open_by_url(spreadsheet_url)
        return spreadsheet.get_worksheet_by_id(worksheet_id)

    attempts = 1

    while True:
        try:
            return execute()
        except gspread.exceptions.APIError as e:
            if e.code != 429 or attempts >= max_attempts:
                raise

            jitter = random.uniform(-jitter_in_seconds, jitter_in_seconds)
            sleep_with_jitter = sleep_per_attempt_in_seconds + jitter

            time.sleep(sleep_with_jitter * attempts)
            attempts = attempts + 1


def get_schemas(config: GoogleSheetsSourceConfig) -> list[tuple[str, int]]:
    """Returns a tuple of worksheets in the form of (title, id)"""

    client = google_sheets_client()
    spreadsheet = client.open_by_url(config.spreadsheet_url)
    worksheets = spreadsheet.worksheets()

    return [(NamingConvention().normalize_identifier(worksheet.title), worksheet.id) for worksheet in worksheets]


def get_schema_incremental_fields(config: GoogleSheetsSourceConfig, worksheet_name: str) -> list[IncrementalField]:
    worksheets = get_schemas(config)
    selected_worksheet = [id for name, id in worksheets if name == worksheet_name]
    if len(selected_worksheet) == 0:
        raise Exception(f'Worksheet titled "{worksheet_name}" can\'t be found')

    worksheet_id = selected_worksheet[0]

    worksheet = _get_worksheet(config.spreadsheet_url, worksheet_id)

    rows = worksheet.get_all_values("1:2")  # Get the first two rows

    if len(rows) > 1 and "id" in rows[0]:
        index_of_id = rows[0].index("id")
        value_of_id_col = rows[1][index_of_id]
        if isinstance(value_of_id_col, int | float):
            return [
                {
                    "label": "id",
                    "field": "id",
                    "type": IncrementalFieldType.Numeric,
                    "field_type": IncrementalFieldType.Numeric,
                }
            ]

    return []


def google_sheets_source(
    config: GoogleSheetsSourceConfig,
    worksheet_name: str,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    worksheets = get_schemas(config)
    selected_worksheet = [id for name, id in worksheets if name == worksheet_name]
    if len(selected_worksheet) == 0:
        raise Exception(f'Worksheet titled "{worksheet_name}" can\'t be found')

    worksheet_id = selected_worksheet[0]

    worksheet = _get_worksheet(config.spreadsheet_url, worksheet_id)

    headers = worksheet.get_all_values("1:1")  # Get the first row
    primary_keys = None
    if len(headers) > 0 and "id" in headers[0]:
        primary_keys = ["id"]

    def get_rows():
        worksheet = _get_worksheet(config.spreadsheet_url, worksheet_id)

        values = worksheet.get_all_records()

        if should_use_incremental_field and db_incremental_field_last_value is not None:
            values = [value for value in values if value.get("id", 0) > db_incremental_field_last_value]

        yield table_from_py_list(values)

    return SourceResponse(name=worksheet_name, items=get_rows(), primary_keys=primary_keys)
