"""Warehouse tables that a notebook cell writes from its result dataframe.

The notebook sandbox writes the cell's dataframe as one Parquet object through a presigned PUT,
then the backend points a self-managed ``DataWarehouseTable`` at that object. The key depends only
on the team and the table name, so each run replaces the object in place and the table keeps the
same ``url_pattern``. PostHog hosts the object in its own data warehouse bucket, so the table
carries no credential, the same as a file upload.
"""

import re

from django.conf import settings
from django.db import transaction

import boto3

from posthog.hogql.database.database import MODELS_NAMESPACE_TABLE_ERROR, Database, is_reserved_models_name

from posthog.models.user import User

from products.data_warehouse.backend.facade.contracts import NotebookTableError
from products.warehouse_sources.backend.facade.hogql import get_view_or_table_by_name
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.facade.tasks import validate_data_warehouse_table_columns
from products.warehouse_sources.backend.facade.types import DataWarehouseTableFormat

NOTEBOOK_TABLES_FOLDER = "notebook_tables"
# The sandbox has to finish the cell and write the Parquet file before this expires.
UPLOAD_URL_EXPIRY_SECONDS = 6 * 60 * 60

_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


def build_notebook_table_s3_key(team_id: int, table_name: str) -> str:
    return f"{NOTEBOOK_TABLES_FOLDER}/team_{team_id}/{table_name}/data.parquet"


def build_notebook_table_url_pattern(team_id: int, table_name: str) -> str:
    return f"https://{settings.DATAWAREHOUSE_BUCKET_DOMAIN}/{build_notebook_table_s3_key(team_id, table_name)}"


def _live_table(team_id: int, table_name: str) -> DataWarehouseTable | None:
    return DataWarehouseTable.objects.filter(team_id=team_id, name=table_name).exclude(deleted=True).first()


def _user(user_id: int | None) -> User | None:
    return User.objects.filter(id=user_id).first() if user_id is not None else None


def validate_notebook_table_name(team_id: int, table_name: str, user_id: int | None) -> None:
    """Raise `NotebookTableError` unless a notebook may write a table with this name.

    A notebook may replace a table that a notebook wrote before, from any notebook in the team.
    It may not take the name of any other table, view, or PostHog table.
    """
    if not settings.DATAWAREHOUSE_BUCKET or not settings.DATAWAREHOUSE_BUCKET_DOMAIN:
        raise NotebookTableError("Saving to a warehouse table isn't available on this instance.")
    if not _TABLE_NAME.fullmatch(table_name):
        raise NotebookTableError(
            "Use a table name that starts with a letter or underscore and has only letters, numbers, and underscores."
        )
    if is_reserved_models_name(table_name):
        raise NotebookTableError(MODELS_NAMESPACE_TABLE_ERROR)
    existing = _live_table(team_id, table_name)
    if existing is not None:
        if existing.url_pattern != build_notebook_table_url_pattern(team_id, table_name):
            raise NotebookTableError(
                f"A table named '{table_name}' already exists and a notebook didn't create it. Choose a different name."
            )
        return
    # has_table only sees what this user may read, so also look the name up team-wide.
    database = Database.create_for(team_id=team_id, user=_user(user_id))
    if database.has_table(table_name) or get_view_or_table_by_name(team_id, table_name):
        raise NotebookTableError(f"A table or view named '{table_name}' already exists. Choose a different name.")


def presign_notebook_table_upload(team_id: int, table_name: str) -> str:
    """A presigned PUT for the table's Parquet object. Call `validate_notebook_table_name` first."""
    if settings.USE_LOCAL_SETUP:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            aws_secret_access_key=settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        )
    else:
        s3 = boto3.client("s3")
    return s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.DATAWAREHOUSE_BUCKET, "Key": build_notebook_table_s3_key(team_id, table_name)},
        ExpiresIn=UPLOAD_URL_EXPIRY_SECONDS,
    )


def save_notebook_table(team_id: int, table_name: str, user_id: int | None) -> str:
    """Point the named table at the Parquet object the sandbox just wrote. Return the table id.

    Creates the table on the first save. A later save keeps the row and reads the columns again,
    because the new dataframe can have a different schema.
    """
    validate_notebook_table_name(team_id, table_name, user_id)
    url_pattern = build_notebook_table_url_pattern(team_id, table_name)
    # Read the columns before the row lock: this is a ClickHouse round trip.
    candidate = DataWarehouseTable(
        team_id=team_id,
        name=table_name,
        format=DataWarehouseTableFormat.Parquet,
        url_pattern=url_pattern,
        created_by=_user(user_id),
    )
    try:
        columns = candidate.get_columns()
    except Exception as err:
        raise NotebookTableError("The saved dataframe couldn't be read back as a table.") from err
    with transaction.atomic():
        table = (
            DataWarehouseTable.objects.select_for_update()
            .filter(team_id=team_id, name=table_name, url_pattern=url_pattern)
            .exclude(deleted=True)
            .first()
        ) or candidate
        table.columns = columns
        table.save()
    validate_data_warehouse_table_columns.delay(team_id, str(table.id))
    return str(table.id)
