"""Helpers for publishing modeled duckgres tables into the ClickHouse-queryable warehouse.

A publish copies one modeled DuckLake table's current state into PostHog's warehouse
bucket as plain parquet (DuckDB COPY TO, executed on the org's duckgres worker) and
registers it as a DataWarehouseTable. Each publish writes a fresh version folder and
repoints the table's url_pattern, so readers never see a half-written folder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from django.conf import settings

from psycopg import sql as psql

if TYPE_CHECKING:
    from types_aiobotocore_s3.type_defs import ObjectIdentifierTypeDef

PUBLISH_WRITE_SECRET_NAME = "posthog_publish_write"

# Schemas that are posthog-managed or DuckDB-internal — never publish candidates.
_EXCLUDED_SCHEMAS = {"information_schema", "pg_catalog", "system"}
_EXCLUDED_SCHEMA_PREFIXES = ("posthog_data_imports", "shadow_")
# Sink marker tables and backfill scratch tables.
_EXCLUDED_TABLE_PREFIXES = ("_posthog_",)
_EXCLUDED_TABLE_SUBSTRINGS = ("__bf_",)


@dataclass(frozen=True)
class ModeledTable:
    schema_name: str
    table_name: str


def publish_folder(team_id: int, publication_id_hex: str) -> str:
    return f"team_{team_id}_publish_{publication_id_hex}"


def publish_s3_uri(folder: str, version: str) -> str:
    return f"{settings.BUCKET_URL}/{folder}/{version}"


def publish_url_pattern(folder: str, version: str) -> str:
    # Mirrors DataWarehouseSavedQuery.url_pattern: BUCKET_URL (s3 scheme) is where
    # writes land; ClickHouse reads over http(s) via DATAWAREHOUSE_BUCKET_DOMAIN.
    if settings.USE_LOCAL_SETUP:
        bucket_name = urlparse(settings.BUCKET_URL).netloc
        return f"http://{settings.DATAWAREHOUSE_BUCKET_DOMAIN}/{bucket_name}/{folder}/{version}/**.parquet"
    return f"https://{settings.DATAWAREHOUSE_BUCKET_DOMAIN}/dlt/{folder}/{version}/**.parquet"


def reserved_backfill_table_names(table_suffix: str | None) -> frozenset[str]:
    """events/persons tables the duckling backfill maintains — posthog-origin, never candidates."""
    if table_suffix:
        return frozenset({f"events_{table_suffix}", f"persons_{table_suffix}"})
    return frozenset({"events", "persons"})


def is_publishable_table(schema_name: str, table_name: str, *, reserved_table_names: frozenset[str]) -> bool:
    if schema_name in _EXCLUDED_SCHEMAS:
        return False
    if schema_name.startswith(_EXCLUDED_SCHEMA_PREFIXES):
        return False
    if table_name.startswith(_EXCLUDED_TABLE_PREFIXES):
        return False
    if any(marker in table_name for marker in _EXCLUDED_TABLE_SUBSTRINGS):
        return False
    if table_name in reserved_table_names:
        return False
    return True


def build_publish_copy_sql(schema_name: str, table_name: str, destination_uri: str) -> psql.Composed:
    return psql.SQL(
        "COPY (SELECT * FROM {}.{}) TO {} (FORMAT PARQUET, COMPRESSION ZSTD, PER_THREAD_OUTPUT TRUE)"
    ).format(psql.Identifier(schema_name), psql.Identifier(table_name), psql.Literal(destination_uri))


def _sql_str(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def build_publish_write_secret_sql(scope: str) -> str:
    """Session secret granting the duckgres worker write access to the publish destination.

    The worker's ambient credentials are scoped to the org's own lake bucket, so writing
    into PostHog's warehouse bucket needs credentials minted from this process's identity,
    scoped to exactly the destination prefix (same pattern as the sink's extract-read
    secret in pipeline_v3/duckgres/processor.py).
    """
    if settings.USE_LOCAL_SETUP:
        endpoint = settings.OBJECT_STORAGE_ENDPOINT.replace("http://", "").replace("https://", "")
        parts = [
            "TYPE S3",
            f"KEY_ID {_sql_str(settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY)}",
            f"SECRET {_sql_str(settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET)}",
            f"ENDPOINT {_sql_str(endpoint)}",
            "URL_STYLE 'path'",
            "USE_SSL false",
            f"SCOPE {_sql_str(scope)}",
        ]
    else:
        import boto3  # noqa: PLC0415 — keeps the heavy dep off the import path

        session = boto3.Session()
        creds = session.get_credentials()
        if creds is None:
            raise RuntimeError("No AWS credentials available to write the publish destination from duckgres")
        frozen = creds.get_frozen_credentials()
        if not frozen.access_key or not frozen.secret_key:
            raise RuntimeError("AWS credential chain resolved without an access key pair")
        parts = [
            "TYPE S3",
            f"KEY_ID {_sql_str(frozen.access_key)}",
            f"SECRET {_sql_str(frozen.secret_key)}",
            f"REGION {_sql_str(session.region_name or 'us-east-1')}",
            f"SCOPE {_sql_str(scope)}",
        ]
        if frozen.token:
            parts.insert(3, f"SESSION_TOKEN {_sql_str(frozen.token)}")

    return f"CREATE OR REPLACE SECRET {PUBLISH_WRITE_SECRET_NAME} ({', '.join(parts)})"


def delete_stale_publish_versions(folder: str, keep_version: str) -> None:
    """Best-effort removal of superseded version folders under the publication's prefix."""
    import boto3  # noqa: PLC0415 — keeps the heavy dep off the import path

    parsed = urlparse(settings.BUCKET_URL)
    bucket = parsed.netloc
    base_prefix = parsed.path.strip("/")
    prefix = f"{base_prefix}/{folder}/" if base_prefix else f"{folder}/"

    client_kwargs: dict[str, Any] = {}
    if settings.USE_LOCAL_SETUP:
        client_kwargs = {
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_access_key_id": settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            "aws_secret_access_key": settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
        }
    s3 = boto3.client("s3", **client_kwargs)

    keep_fragment = f"/{keep_version}/"
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        stale: list[ObjectIdentifierTypeDef] = [
            {"Key": obj["Key"]} for obj in page.get("Contents", []) if keep_fragment not in obj["Key"]
        ]
        if stale:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": stale})
