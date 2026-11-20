"""Publish notebook dataframes as hosted warehouse tables."""

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q

import boto3
from botocore.config import Config

from posthog.hogql.database.database import MODELS_NAMESPACE_TABLE_ERROR, Database, is_reserved_models_name

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_warehouse.backend.facade.contracts import NotebookTableError
from products.warehouse_sources.backend.facade.api import MAX_FILE_UPLOAD_SIZE_BYTES
from products.warehouse_sources.backend.facade.hogql import get_view_or_table_by_name
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.facade.tasks import validate_data_warehouse_table_columns
from products.warehouse_sources.backend.facade.types import DataWarehouseTableFormat

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client as Boto3StubsS3Client
    from types_boto3_s3 import S3Client as TypesBoto3S3Client

    # Both installed boto3 stub packages describe the same runtime client.
    S3Client = Boto3StubsS3Client | TypesBoto3S3Client

NOTEBOOK_TABLES_FOLDER = "notebook_tables"
# A cell can run for six hours, and the sandbox writes the Parquet file only after the cell
# finishes. The extra hour keeps the URL valid for that upload.
UPLOAD_URL_EXPIRY_SECONDS = 7 * 60 * 60

_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


def build_notebook_table_s3_key(team_id: int, table_name: str, run_id: str) -> str:
    return f"{NOTEBOOK_TABLES_FOLDER}/team_{team_id}/{table_name}/versions/{run_id}.parquet"


def build_notebook_table_staging_s3_key(team_id: int, table_name: str, run_id: str) -> str:
    return f"{NOTEBOOK_TABLES_FOLDER}/team_{team_id}/{table_name}/staging/{run_id}.parquet"


def _object_url(key: str) -> str:
    # Local object storage serves plain HTTP with the bucket in the path, the same form that
    # DataWarehouseSavedQuery.url_pattern uses in local setup.
    if settings.USE_LOCAL_SETUP:
        return f"http://{settings.DATAWAREHOUSE_BUCKET_DOMAIN}/{settings.DATAWAREHOUSE_BUCKET}/{key}"
    return f"https://{settings.DATAWAREHOUSE_BUCKET_DOMAIN}/{key}"


def _version_prefix(team_id: int, table_name: str) -> str:
    return _object_url(f"{NOTEBOOK_TABLES_FOLDER}/team_{team_id}/{table_name}/versions/")


def _notebook_table_storage(team_id: int, table_name: str) -> Q:
    prefix = _version_prefix(team_id, table_name)
    return Q(url_pattern__startswith=prefix) | Q(url_pattern=prefix.removesuffix("versions/") + "data.parquet")


def _delete_object(s3: "S3Client", key: str) -> None:
    try:
        s3.delete_object(Bucket=settings.DATAWAREHOUSE_BUCKET, Key=key)
    except Exception as err:
        capture_exception(err)


def _live_table(team_id: int, table_name: str) -> DataWarehouseTable | None:
    return DataWarehouseTable.objects.filter(team_id=team_id, name=table_name).exclude(deleted=True).first()


def _user(user_id: int | None) -> User | None:
    if user_id is None:
        return None
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist as err:
        raise NotebookTableError("The user who started this run no longer exists.") from err


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
        prefix = _version_prefix(team_id, table_name)
        if (
            not existing.url_pattern.startswith(prefix)
            and existing.url_pattern != prefix.removesuffix("versions/") + "data.parquet"
        ):
            raise NotebookTableError(
                f"A table named '{table_name}' already exists and a notebook didn't create it. Choose a different name."
            )
        if user is not None and not _access(user, team_id).check_access_level_for_object(existing, "editor"):
            raise NotebookTableError(f"You don't have permission to replace the warehouse table '{table_name}'.")
        return
    if user is not None and not _access(user, team_id).check_access_level_for_resource("warehouse_table", "editor"):
        raise NotebookTableError("You don't have permission to create warehouse tables.")
    if (
        DataWarehouseTable.objects.filter(team_id=team_id)
        .filter(_notebook_table_storage(team_id, table_name))
        .exclude(deleted=True)
        .exists()
    ):
        raise NotebookTableError(
            f"A renamed table still uses the storage for the name '{table_name}'. Choose a different name."
        )
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


def presign_notebook_table_upload(team_id: int, table_name: str, run_id: str) -> dict[str, Any]:
    return _s3_client(_sandbox_object_storage_endpoint()).generate_presigned_post(
        Bucket=settings.DATAWAREHOUSE_BUCKET,
        Key=build_notebook_table_staging_s3_key(team_id, table_name, run_id),
        Conditions=[["content-length-range", 1, MAX_FILE_UPLOAD_SIZE_BYTES]],
        ExpiresIn=UPLOAD_URL_EXPIRY_SECONDS,
    )


def save_notebook_table(team_id: int, table_name: str, user_id: int | None, run_id: str) -> str:
    """Publish the run's Parquet object and its schema together."""
    validate_notebook_table_name(team_id, table_name, user_id)
    s3 = _s3_client()
    bucket = settings.DATAWAREHOUSE_BUCKET
    staging_key = build_notebook_table_staging_s3_key(team_id, table_name, run_id)
    key = build_notebook_table_s3_key(team_id, table_name, run_id)
    url_pattern = _object_url(key)
    prefix = _version_prefix(team_id, table_name)
    try:
        with transaction.atomic():
            # Serializes saves of one name, so two first saves can't each create a table, and the
            # object and the columns always come from the same run.
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [team_id, f"notebook_table:{table_name}"]
                )
            # Read again under the lock, because a table can be created or renamed after dispatch
            # checked the name. A row with only the name or only the URL is another table.
            claimants = list(
                DataWarehouseTable.objects.select_for_update(of=("self",))
                .filter(team_id=team_id)
                .filter(Q(name=table_name) | _notebook_table_storage(team_id, table_name))
                .exclude(deleted=True)
            )
            if len(claimants) > 1 or any(row.name != table_name for row in claimants):
                raise NotebookTableError(f"Another table now uses the name '{table_name}'. Choose a different name.")
            if claimants:
                validate_notebook_table_name(team_id, table_name, user_id)
            table = (
                claimants[0]
                if claimants
                else DataWarehouseTable(
                    team_id=team_id,
                    name=table_name,
                    created_by=_user(user_id),
                )
            )
            previous = table.url_pattern
            if previous == url_pattern:
                return str(table.id)
            # Runs are dispatched with UUIDv7 IDs. Queue delays must not let older data replace a newer version.
            if previous.startswith(prefix) and previous > url_pattern:
                raise NotebookTableError("A newer run already saved this table.")
            staged_object = s3.head_object(Bucket=bucket, Key=staging_key)
            if staged_object["ContentLength"] > MAX_FILE_UPLOAD_SIZE_BYTES:
                raise NotebookTableError("The dataframe exceeds the warehouse upload size limit.")
            s3.copy_object(
                Bucket=bucket,
                Key=key,
                CopySource={"Bucket": bucket, "Key": staging_key},
                CopySourceIfMatch=staged_object["ETag"],
            )
            table.url_pattern = url_pattern
            table.format = DataWarehouseTableFormat.Parquet
            try:
                columns = table.get_columns()
            except Exception as err:
                _delete_object(s3, key)
                raise NotebookTableError("The saved dataframe couldn't be read back as a table.") from err
            try:
                table.set_columns(columns)
                table.save(internally_computed_url_pattern=True)
            except Exception:
                _delete_object(s3, key)
                raise
            if previous:
                previous_key = previous.removeprefix(_object_url(""))
                transaction.on_commit(lambda: _delete_object(s3, previous_key))
    finally:
        _delete_object(s3, staging_key)
    try:
        validate_data_warehouse_table_columns.delay(team_id, str(table.id))
    except Exception as err:
        capture_exception(err)
    return str(table.id)
