"""Helpers for publishing modeled duckgres tables into the ClickHouse-queryable warehouse.

A publish copies one modeled DuckLake table's current state into a versioned parquet
folder under the org's own managed-warehouse bucket (DuckDB COPY TO, executed on the
org's duckgres worker with its ambient credentials) and registers it as a
DataWarehouseTable. Each publish writes a fresh version folder and repoints the
table's url_pattern, so readers never see a half-written folder.

Published data deliberately stays in the org's bucket: the worker needs no injected
PostHog credentials to write it, and ClickHouse reads it cross-account through the
duckling bucket policy (see the crossplane duckling composition in PostHog/charts),
which is scoped to PUBLISHED_PREFIX.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.conf import settings

from psycopg import sql as psql

if TYPE_CHECKING:
    from types_aiobotocore_s3.type_defs import ObjectIdentifierTypeDef

# Top-level key prefix for published snapshots in the org bucket. Leading underscores
# keep it collision-free: sanitize_ducklake_identifier strips them, so no DuckLake
# schema directory can ever shadow it (same convention as storage.STAGING_PREFIX).
# The duckling bucket policy's ClickHouse read grant is scoped to this prefix — the
# charts crossplane composition must reference the same literal.
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
    # ClickHouse reads the org bucket over https; its EC2 role is granted GetObject +
    # prefix-scoped ListBucket by the duckling bucket policy, so no credentials are
    # stored on the DataWarehouseTable.
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


def delete_stale_publish_versions(bucket: str, folder: str, keep_versions: Collection[str]) -> None:
    """Best-effort removal of version folders under the publication's prefix.

    Every object whose key is not inside one of keep_versions is deleted; an empty
    keep set removes the whole folder (used once a publication is deleted). Runs
    with the temporal worker's own AWS identity; cross-account delete on the org
    bucket is granted (scoped to PUBLISHED_PREFIX) by the duckling bucket policy.
    """
    import boto3  # noqa: PLC0415 — keeps the heavy dep off the import path

    client_kwargs: dict[str, Any] = {}
    if settings.USE_LOCAL_SETUP:
        client_kwargs = {
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_access_key_id": settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            "aws_secret_access_key": settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
        }
    s3 = boto3.client("s3", **client_kwargs)

    prefix = f"{PUBLISHED_PREFIX}/{folder}/"
    keep_fragments = [f"/{version}/" for version in keep_versions]
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        stale: list[ObjectIdentifierTypeDef] = [
            {"Key": obj["Key"]}
            for obj in page.get("Contents", [])
            if not any(fragment in obj["Key"] for fragment in keep_fragments)
        ]
        if stale:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": stale})
