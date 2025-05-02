import contextlib
from collections import defaultdict

from google.api_core.exceptions import Forbidden
from google.cloud import bigquery
from google.oauth2 import service_account

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.warehouse.types import IncrementalFieldType


@contextlib.contextmanager
def bigquery_client(project_id: str, private_key: str, private_key_id: str, client_email: str, token_uri: str):
    """Manage a BigQuery client."""
    credentials = service_account.Credentials.from_service_account_info(
        {
            "private_key": private_key,
            "private_key_id": private_key_id,
            "token_uri": token_uri,
            "client_email": client_email,
            "project_id": project_id,
        },
        scopes=["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/cloud-platform"],
    )
    client = bigquery.Client(
        project=project_id,
        credentials=credentials,
    )

    try:
        yield client
    finally:
        client.close()


def delete_table(
    table_id: str, project_id: str, private_key: str, private_key_id: str, client_email: str, token_uri: str
) -> None:
    with bigquery_client(project_id, private_key, private_key_id, client_email, token_uri) as bq:
        bq.delete_table(table_id, not_found_ok=True)


def delete_all_temp_destination_tables(
    dataset_id: str,
    table_prefix: str,
    project_id: str,
    private_key: str,
    private_key_id: str,
    client_email: str,
    token_uri: str,
    logger: None | FilteringBoundLogger,
) -> None:
    with bigquery_client(project_id, private_key, private_key_id, client_email, token_uri) as bq:
        try:
            tables = bq.list_tables(bq.dataset(dataset_id))
            for table in tables:
                if table.table_id.startswith(table_prefix):
                    bq.delete_table(table.reference)
                    if logger:
                        logger.debug(f"Deleted bigquery table {table.table_id}")
        except Exception as e:
            capture_exception(e)


def get_schemas(
    dataset_id: str,
    project_id: str,
    private_key: str,
    private_key_id: str,
    client_email: str,
    token_uri: str,
    logger: FilteringBoundLogger | None = None,
) -> dict[str, list[tuple[str, str]]]:
    schema_list = defaultdict(list)

    with bigquery_client(project_id, private_key, private_key_id, client_email, token_uri) as bq:
        query = bq.query(
            f"SELECT table_name, column_name, data_type FROM `{dataset_id}.INFORMATION_SCHEMA.COLUMNS` ORDER BY table_name ASC"
        )
        try:
            rows = query.result()
        except Forbidden:
            if logger:
                logger.warning(
                    "Could not obtain new schemas from BigQuery due to missing permissions on '%s.INFORMATION_SCHEMA.COLUMNS'",
                    dataset_id,
                )
            return {}

        for row in rows:
            schema_list[row.table_name].append((row.column_name, row.data_type))

    return schema_list


def filter_incremental_fields(columns: list[tuple[str, str]]) -> list[tuple[str, IncrementalFieldType]]:
    results: list[tuple[str, IncrementalFieldType]] = []
    for column_name, type in columns:
        type = type.upper()
        if type.startswith("TIMESTAMP"):
            results.append((column_name, IncrementalFieldType.Timestamp))
        elif type.startswith("DATE"):
            results.append((column_name, IncrementalFieldType.Date))
        elif type.startswith("DATETIME"):
            results.append((column_name, IncrementalFieldType.DateTime))
        elif (
            type.startswith("INT64")
            or type.startswith("NUMERIC")
            or type.startswith("BIGNUMERIC")
            or type.startswith("INT")
            or type.startswith("SMALLINT")
            or type.startswith("INTEGER")
            or type.startswith("BIGINT")
            or type.startswith("TINYINT")
            or type.startswith("BYTEINT")
        ):
            results.append((column_name, IncrementalFieldType.Integer))

    return results


def validate_credentials(dataset_id: str, key_file: dict[str, str]) -> bool:
    project_id = key_file.get("project_id")
    private_key = key_file.get("private_key")
    private_key_id = key_file.get("private_key_id")
    client_email = key_file.get("client_email")
    token_uri = key_file.get("token_uri")

    if not project_id or not private_key or not private_key_id or not client_email or not token_uri:
        return False

    with bigquery_client(project_id, private_key, private_key_id, client_email, token_uri) as bq:
        try:
            bq.list_tables(bq.dataset(dataset_id), retry=bigquery.DEFAULT_RETRY.with_timeout(5))
            return True
        except Exception as e:
            capture_exception(e)
            return False
