"""Warehouse tables that a notebook cell writes from its result dataframe.

The notebook sandbox writes the cell's dataframe as one Parquet object to a per-run staging key
through a presigned PUT. The backend reads the staged object's columns, then copies it to the
live key and points a self-managed ``DataWarehouseTable`` at it. The live key depends only on the
team and the table name, so each run replaces the object in place and the table keeps the same
``url_pattern``. PostHog hosts the object in its own data warehouse bucket, so the table carries
no credential, the same as a file upload.
"""

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from django.conf import settings
from django.db import connection, transaction

import boto3
from botocore.config import Config

from posthog.hogql.database.database import MODELS_NAMESPACE_TABLE_ERROR, Database, is_reserved_models_name

from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_warehouse.backend.facade.contracts import NotebookTableError
from products.warehouse_sources.backend.facade.hogql import get_view_or_table_by_name
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.facade.tasks import validate_data_warehouse_table_columns
from products.warehouse_sources.backend.facade.types import DataWarehouseTableFormat

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

NOTEBOOK_TABLES_FOLDER = "notebook_tables"
# The sandbox has to finish the cell and write the Parquet file before this expires.
UPLOAD_URL_EXPIRY_SECONDS = 6 * 60 * 60

_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


def build_notebook_table_s3_key(team_id: int, table_name: str) -> str:
    return f"{NOTEBOOK_TABLES_FOLDER}/team_{team_id}/{table_name}/data.parquet"


def build_notebook_table_staging_s3_key(team_id: int, table_name: str, run_id: str) -> str:
    return f"{NOTEBOOK_TABLES_FOLDER}/team_{team_id}/{table_name}/staging/{run_id}.parquet"


def _object_url(key: str) -> str:
    # Local object storage serves plain HTTP with the bucket in the path, the same form that
    # DataWarehouseSavedQuery.url_pattern uses in local setup.
    if settings.USE_LOCAL_SETUP:
        return f"http://{settings.DATAWAREHOUSE_BUCKET_DOMAIN}/{settings.DATAWAREHOUSE_BUCKET}/{key}"
    return f"https://{settings.DATAWAREHOUSE_BUCKET_DOMAIN}/{key}"


def build_notebook_table_url_pattern(team_id: int, table_name: str) -> str:
    return _object_url(build_notebook_table_s3_key(team_id, table_name))


def _live_table(team_id: int, table_name: str) -> DataWarehouseTable | None:
    return DataWarehouseTable.objects.filter(team_id=team_id, name=table_name).exclude(deleted=True).first()


def _user(user_id: int | None) -> User | None:
    return User.objects.filter(id=user_id).first() if user_id is not None else None


def _access(user: User, team_id: int) -> UserAccessControl:
    return UserAccessControl(user=user, team=Team.objects.get(id=team_id))


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
    user = _user(user_id)
    existing = _live_table(team_id, table_name)
    if existing is not None:
        if existing.url_pattern != build_notebook_table_url_pattern(team_id, table_name):
            raise NotebookTableError(
                f"A table named '{table_name}' already exists and a notebook didn't create it. Choose a different name."
            )
        if user is not None and not _access(user, team_id).check_access_level_for_object(existing, "editor"):
            raise NotebookTableError(f"You don't have permission to replace the warehouse table '{table_name}'.")
        return
    if user is not None and not _access(user, team_id).check_access_level_for_resource("warehouse_table", "editor"):
        raise NotebookTableError("You don't have permission to create warehouse tables.")
    # has_table only sees what this user may read, so also look the name up team-wide.
    database = Database.create_for(team_id=team_id, user=user)
    if database.has_table(table_name) or get_view_or_table_by_name(team_id, table_name):
        raise NotebookTableError(f"A table or view named '{table_name}' already exists. Choose a different name.")


def _s3_client(endpoint_url: str | None = None) -> "S3Client":
    if settings.USE_LOCAL_SETUP:
        return boto3.client(
            "s3",
            aws_access_key_id=settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            aws_secret_access_key=settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
            endpoint_url=endpoint_url or settings.OBJECT_STORAGE_ENDPOINT,
            config=Config(signature_version="s3v4"),
        )
    # botocore presigns with SigV2 unless told otherwise. SeaweedFS and S3 buckets created
    # after June 2020 accept only SigV4.
    return boto3.client("s3", config=Config(signature_version="s3v4"))


def _sandbox_object_storage_endpoint() -> str | None:
    # A local Docker kernel can't resolve the compose hostname, and the host is part of the
    # SigV4 signature, so the URL has to be signed for the address the container dials.
    if not settings.DEBUG or not settings.OBJECT_STORAGE_ENDPOINT:
        return None
    parsed = urlparse(settings.OBJECT_STORAGE_ENDPOINT)
    return parsed._replace(netloc=f"host.docker.internal:{parsed.port or 80}").geturl()


def presign_notebook_table_upload(team_id: int, table_name: str, run_id: str) -> str:
    """A presigned PUT for the run's staging object. Call `validate_notebook_table_name` first.

    The sandbox writes to a staging key, never to the live object, so a dataframe that can't be
    read as a table never replaces the data a table already serves.
    """
    return _s3_client(_sandbox_object_storage_endpoint()).generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.DATAWAREHOUSE_BUCKET,
            "Key": build_notebook_table_staging_s3_key(team_id, table_name, run_id),
        },
        ExpiresIn=UPLOAD_URL_EXPIRY_SECONDS,
    )


def save_notebook_table(team_id: int, table_name: str, user_id: int | None, run_id: str) -> str:
    """Publish the run's staged Parquet object as the named table. Return the table id.

    Reads the columns from the staged object first. Only a readable object replaces the live one.
    Creates the table on the first save. A later save keeps the row and reads the columns again,
    because the new dataframe can have a different schema.
    """
    validate_notebook_table_name(team_id, table_name, user_id)
    s3 = _s3_client()
    bucket = settings.DATAWAREHOUSE_BUCKET
    staging_key = build_notebook_table_staging_s3_key(team_id, table_name, run_id)
    staged = DataWarehouseTable(
        team_id=team_id,
        name=table_name,
        format=DataWarehouseTableFormat.Parquet,
        url_pattern=_object_url(staging_key),
    )
    try:
        columns = staged.get_columns()
    except Exception as err:
        s3.delete_object(Bucket=bucket, Key=staging_key)
        raise NotebookTableError("The saved dataframe couldn't be read back as a table.") from err

    url_pattern = build_notebook_table_url_pattern(team_id, table_name)
    with transaction.atomic():
        # Serializes saves of one name, so two first saves can't each create a table, and the
        # object and the columns always come from the same run.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [team_id, f"notebook_table:{table_name}"])
        table = (
            DataWarehouseTable.objects.select_for_update(of=("self",))
            .filter(team_id=team_id, name=table_name, url_pattern=url_pattern)
            .exclude(deleted=True)
            .first()
        ) or DataWarehouseTable(
            team_id=team_id,
            name=table_name,
            format=DataWarehouseTableFormat.Parquet,
            url_pattern=url_pattern,
            created_by=_user(user_id),
        )
        s3.copy({"Bucket": bucket, "Key": staging_key}, bucket, build_notebook_table_s3_key(team_id, table_name))
        table.columns = columns
        table.save()
    s3.delete_object(Bucket=bucket, Key=staging_key)
    validate_data_warehouse_table_columns.delay(team_id, str(table.id))
    return str(table.id)
