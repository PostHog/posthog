"""Publish modeled Duckgres tables as versioned parquet snapshots.

Each publish writes a fresh folder and repoints the warehouse table only after
the copy completes.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.conf import settings

from psycopg import sql as psql

if TYPE_CHECKING:
    from types_aiobotocore_s3.type_defs import ObjectIdentifierTypeDef

# Leading underscores prevent collisions because sanitized DuckLake schema
# directories cannot start with them. The bucket policy uses this same prefix.
PUBLISHED_PREFIX = "__posthog_published"

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


def publish_s3_uri(bucket: str, folder: str, version: str) -> str:
    return f"s3://{bucket}/{PUBLISHED_PREFIX}/{folder}/{version}"


def publish_url_pattern(bucket: str, bucket_region: str, folder: str, version: str) -> str:
    if settings.USE_LOCAL_SETUP:
        endpoint = settings.OBJECT_STORAGE_ENDPOINT.replace("http://", "").replace("https://", "")
        return f"http://{endpoint}/{bucket}/{PUBLISHED_PREFIX}/{folder}/{version}/**.parquet"
    return f"https://{bucket}.s3.{bucket_region}.amazonaws.com/{PUBLISHED_PREFIX}/{folder}/{version}/**.parquet"


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


def _s3_client() -> Any:
    import boto3  # noqa: PLC0415 — keeps the heavy dep off the import path

    client_kwargs: dict[str, Any] = {}
    if settings.USE_LOCAL_SETUP:
        client_kwargs = {
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_access_key_id": settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            "aws_secret_access_key": settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
        }
    return boto3.client("s3", **client_kwargs)


def delete_stale_publish_versions(
    bucket: str, folder: str, keep_versions: Collection[str], *, min_age_seconds: int = 0
) -> None:
    """Delete objects outside kept versions once they are old enough.

    An empty keep set removes the whole publication folder. The age buffer
    protects readers that resolved the old URL just before a repoint.
    """
    s3 = _s3_client()

    prefix = f"{PUBLISHED_PREFIX}/{folder}/"
    keep_fragments = [f"/{version}/" for version in keep_versions]
    min_written_at = dt.datetime.now(dt.UTC).timestamp() - min_age_seconds
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        stale: list[ObjectIdentifierTypeDef] = []
        for obj in page.get("Contents", []):
            key: str = obj["Key"]
            if any(fragment in key for fragment in keep_fragments):
                continue
            if min_age_seconds > 0:
                version = key[len(prefix) :].split("/", 1)[0]
                try:
                    written_at = dt.datetime.strptime(version, "%Y%m%d%H%M%S").replace(tzinfo=dt.UTC).timestamp()
                except ValueError:
                    written_at = 0
                if written_at > min_written_at:
                    continue
            stale.append({"Key": key})
        if stale:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": stale})


def sum_publish_version_size_bytes(bucket: str, folder: str, version: str) -> int:
    """Return the total object size under a published version folder."""
    s3 = _s3_client()

    total = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{PUBLISHED_PREFIX}/{folder}/{version}/"):
        total += sum(obj.get("Size", 0) for obj in page.get("Contents", []))
    return total
