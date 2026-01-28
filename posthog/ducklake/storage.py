"""Centralized DuckLake object-storage credential handling.

This module provides a single entry point for all DuckLake storage credentials,
eliminating ad-hoc helpers spread across Temporal workflows and data warehouse utilities.

Usage:
    from posthog.ducklake.storage import DuckLakeStorageConfig, configure_connection

    # Get storage config from runtime environment
    storage_config = DuckLakeStorageConfig.from_runtime()

    # Configure a DuckDB connection with S3 credentials
    configure_connection(conn, storage_config)

    # Get options for deltalake library
    options = storage_config.to_deltalake_options()
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from posthog.ducklake.common import (
    escape as ducklake_escape,
    get_config,
)

if TYPE_CHECKING:
    import duckdb


def _get_django_settings():
    """Lazy import Django settings to allow CLI tools to work without Django."""
    try:
        from django.conf import settings

        return settings
    except Exception:
        return None


def _get_boto3_credentials() -> tuple[str, str, str | None]:
    """Fetch AWS credentials via boto3.

    This is a workaround for DuckDB's CREDENTIAL_CHAIN not supporting
    IRSA (Web Identity Token) authentication. boto3 properly supports IRSA,
    so we use it to fetch credentials and pass them explicitly to DuckDB.

    See: https://github.com/duckdb/duckdb-aws/issues/31

    Returns:
        Tuple of (access_key, secret_key, session_token).
        session_token may be None for static credentials.
    """
    import boto3

    session = boto3.Session()
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("No AWS credentials available via boto3")
    frozen = credentials.get_frozen_credentials()
    if frozen.access_key is None or frozen.secret_key is None:
        raise RuntimeError("AWS credentials missing access_key or secret_key")
    return frozen.access_key, frozen.secret_key, frozen.token


def _get_cross_account_credentials(role_arn: str, external_id: str | None = None) -> tuple[str, str, str]:
    """Assume a cross-account IAM role and return temporary credentials.

    Args:
        role_arn: The ARN of the role to assume in the destination account
        external_id: Optional external ID for the role assumption (recommended for security)

    Returns:
        Tuple of (access_key, secret_key, session_token)
    """
    import boto3

    sts = boto3.client("sts")
    assume_role_kwargs: dict[str, str | int] = {
        "RoleArn": role_arn,
        "RoleSessionName": "ducklake-cross-account",
        "DurationSeconds": 3600,
    }
    if external_id:
        assume_role_kwargs["ExternalId"] = external_id

    response = sts.assume_role(**assume_role_kwargs)
    creds = response["Credentials"]
    return creds["AccessKeyId"], creds["SecretAccessKey"], creds["SessionToken"]


def normalize_endpoint(endpoint: str) -> tuple[str, bool]:
    """Normalize object storage endpoint URL.

    Extracts the host from a URL and determines SSL usage.

    Args:
        endpoint: The endpoint URL (e.g., "http://localhost:19000" or "localhost:19000")

    Returns:
        Tuple of (normalized_host, use_ssl)
    """
    value = endpoint.strip()
    if not value:
        return "", True

    if "://" in value:
        parsed = urlparse(value)
        normalized = parsed.netloc or parsed.path
        use_ssl = parsed.scheme.lower() == "https"
    else:
        use_ssl = value.lower().startswith("https")
        normalized = value.rstrip("/")

    return normalized.rstrip("/") or "", use_ssl


@dataclasses.dataclass(frozen=True)
class DuckLakeStorageConfig:
    """Configuration for DuckLake object storage access.

    This dataclass encapsulates all credentials and settings needed to access
    DuckLake storage, providing consistent serialization for DuckDB secrets,
    deltalake options, and boto3/s3fs clients.

    Use DuckLakeStorageConfig.from_runtime() to create an instance from the
    current runtime environment.
    """

    access_key: str
    secret_key: str
    region: str
    endpoint: str
    use_ssl: bool
    url_style: str
    is_local: bool

    @classmethod
    def from_runtime(cls, *, use_local_setup: bool | None = None) -> DuckLakeStorageConfig:
        """Create storage config from current runtime environment.

        This factory method encapsulates the USE_LOCAL_SETUP branching logic,
        loading credentials from environment variables for local dev or falling
        back to IRSA credential chain for production.

        Args:
            use_local_setup: Override for USE_LOCAL_SETUP setting. If None,
                reads from Django settings or defaults to True for CLI tools.

        Returns:
            DuckLakeStorageConfig instance with appropriate credentials.
        """
        config = get_config()
        settings = _get_django_settings()

        if use_local_setup is None:
            use_local_setup = getattr(settings, "USE_LOCAL_SETUP", True) if settings else True

        access_key = config.get("DUCKLAKE_S3_ACCESS_KEY", "")
        secret_key = config.get("DUCKLAKE_S3_SECRET_KEY", "")
        region = config.get("DUCKLAKE_BUCKET_REGION", "us-east-1")

        raw_endpoint = getattr(settings, "OBJECT_STORAGE_ENDPOINT", "") if settings else ""

        if use_local_setup:
            normalized_endpoint, use_ssl = normalize_endpoint(raw_endpoint or "")
            return cls(
                access_key=access_key,
                secret_key=secret_key,
                region=region,
                endpoint=normalized_endpoint,
                use_ssl=use_ssl,
                url_style="path",
                is_local=True,
            )
        else:
            return cls(
                access_key="",
                secret_key="",
                region=region,
                endpoint="",
                use_ssl=True,
                url_style="path",
                is_local=False,
            )

    def to_duckdb_secret_sql(self) -> str:
        """Generate DuckDB CREATE SECRET SQL statement.

        Returns:
            SQL statement to create the S3 secret.
        """
        secret_name = "ducklake_s3"
        if not self.is_local:
            # Workaround: DuckDB's CREDENTIAL_CHAIN doesn't support IRSA (Web Identity Token).
            # Fetch credentials via boto3 which properly supports IRSA.
            # See: https://github.com/duckdb/duckdb-aws/issues/31
            access_key, secret_key, session_token = _get_boto3_credentials()
            secret_parts = [
                "TYPE S3",
                f"KEY_ID '{ducklake_escape(access_key)}'",
                f"SECRET '{ducklake_escape(secret_key)}'",
            ]
            if session_token:
                secret_parts.append(f"SESSION_TOKEN '{ducklake_escape(session_token)}'")
            if self.region:
                secret_parts.append(f"REGION '{ducklake_escape(self.region)}'")
            return f"CREATE OR REPLACE SECRET {secret_name} ({', '.join(secret_parts)})"

        secret_parts = ["TYPE S3"]
        if self.access_key:
            secret_parts.append(f"KEY_ID '{ducklake_escape(self.access_key)}'")
        if self.secret_key:
            secret_parts.append(f"SECRET '{ducklake_escape(self.secret_key)}'")
        if self.region:
            secret_parts.append(f"REGION '{ducklake_escape(self.region)}'")
        if self.endpoint:
            secret_parts.append(f"ENDPOINT '{ducklake_escape(self.endpoint)}'")
        secret_parts.append(f"USE_SSL {'true' if self.use_ssl else 'false'}")
        secret_parts.append(f"URL_STYLE '{ducklake_escape(self.url_style)}'")

        return f"CREATE OR REPLACE SECRET {secret_name} ({', '.join(secret_parts)})"

    def to_duckdb_scoped_secret_sql(
        self,
        secret_name: str,
        scope: str,
        access_key: str,
        secret_key: str,
        session_token: str | None = None,
        region: str | None = None,
    ) -> str:
        """Generate a scoped DuckDB CREATE SECRET statement.

        DuckDB scoped secrets allow different credentials for different S3 paths.
        The secret with the most specific matching scope is used for each operation.

        Args:
            secret_name: Unique name for this secret
            scope: S3 bucket scope (e.g., 's3://bucket-name')
            access_key: AWS access key
            secret_key: AWS secret key
            session_token: Optional session token for temporary credentials
            region: AWS region (defaults to self.region)

        Returns:
            SQL statement to create the scoped S3 secret
        """
        effective_region = region or self.region
        if not effective_region:
            raise ValueError("Region is required for scoped S3 secrets")

        secret_parts = [
            "TYPE S3",
            f"KEY_ID '{ducklake_escape(access_key)}'",
            f"SECRET '{ducklake_escape(secret_key)}'",
        ]
        if session_token:
            secret_parts.append(f"SESSION_TOKEN '{ducklake_escape(session_token)}'")
        secret_parts.append(f"REGION '{ducklake_escape(effective_region)}'")
        secret_parts.append(f"SCOPE '{ducklake_escape(scope)}'")

        return f"CREATE OR REPLACE SECRET {secret_name} ({', '.join(secret_parts)})"

    def to_deltalake_options(self) -> dict[str, str]:
        """Generate storage options for deltalake library.

        Returns:
            Dict of storage options to pass to deltalake.DeltaTable.
        """
        options: dict[str, str] = {
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

        if not self.is_local:
            if self.region:
                options["AWS_DEFAULT_REGION"] = self.region
            return options

        if self.access_key:
            options["aws_access_key_id"] = self.access_key
        if self.secret_key:
            options["aws_secret_access_key"] = self.secret_key
        if self.region:
            options["region_name"] = self.region
            options["AWS_DEFAULT_REGION"] = self.region
        if self.endpoint:
            settings = _get_django_settings()
            raw_endpoint = getattr(settings, "OBJECT_STORAGE_ENDPOINT", "") if settings else ""
            options["endpoint_url"] = raw_endpoint or self.endpoint
            options["AWS_ALLOW_HTTP"] = "true"

        return {key: value for key, value in options.items() if value}


def configure_connection(
    conn: duckdb.DuckDBPyConnection,
    storage_config: DuckLakeStorageConfig | None = None,
    *,
    install_extensions: bool = True,
) -> None:
    """Configure DuckDB connection for DuckLake storage access.

    Installs and loads necessary extensions (httpfs, delta) and creates the
    S3 secret for accessing object storage.

    Args:
        conn: DuckDB connection to configure.
        storage_config: Storage config to use. If None, creates one from runtime.
        install_extensions: Whether to install httpfs and delta extensions.
    """
    if storage_config is None:
        storage_config = DuckLakeStorageConfig.from_runtime()

    if install_extensions:
        conn.execute("INSTALL ducklake")
        conn.execute("INSTALL httpfs")
        conn.execute("INSTALL delta")

    conn.execute("LOAD ducklake")
    conn.execute("LOAD httpfs")
    conn.execute("LOAD delta")
    conn.execute(storage_config.to_duckdb_secret_sql())


@dataclasses.dataclass(frozen=True)
class CrossAccountDestination:
    """Configuration for a cross-account S3 destination.

    Used with configure_cross_account_connection() to set up DuckDB credentials
    for writing to S3 buckets in different AWS accounts.

    Attributes:
        role_arn: The ARN of the IAM role to assume in the destination account
        bucket_name: The name of the destination S3 bucket
        external_id: Optional external ID for role assumption (recommended for security)
        region: Optional AWS region for the destination bucket
    """

    role_arn: str
    bucket_name: str
    external_id: str | None = None
    region: str | None = None


def configure_cross_account_connection(
    conn: duckdb.DuckDBPyConnection,
    source_storage_config: DuckLakeStorageConfig | None = None,
    destinations: list[CrossAccountDestination] | None = None,
    *,
    install_extensions: bool = True,
) -> None:
    """Configure DuckDB connection for cross-account S3 access.

    Sets up scoped secrets so DuckDB automatically uses the correct credentials
    based on the S3 path being accessed. Source bucket uses IRSA credentials,
    while destination buckets use credentials from assumed cross-account roles.

    Args:
        conn: DuckDB connection to configure
        source_storage_config: Storage config for the source bucket (uses IRSA credentials).
            If None, creates one from runtime.
        destinations: List of cross-account destinations to configure. Each destination
            will have its role assumed and a scoped secret created for its bucket.
        install_extensions: Whether to install DuckDB extensions
    """
    if source_storage_config is None:
        source_storage_config = DuckLakeStorageConfig.from_runtime()

    if install_extensions:
        conn.execute("INSTALL ducklake")
        conn.execute("INSTALL httpfs")
        conn.execute("INSTALL delta")

    conn.execute("LOAD ducklake")
    conn.execute("LOAD httpfs")
    conn.execute("LOAD delta")

    # Set up source credentials (from IRSA or local config)
    conn.execute(source_storage_config.to_duckdb_secret_sql())

    # Set up destination credentials (via cross-account role assumption)
    if destinations:
        for i, dest in enumerate(destinations):
            access_key, secret_key, session_token = _get_cross_account_credentials(
                dest.role_arn,
                external_id=dest.external_id,
            )
            secret_sql = source_storage_config.to_duckdb_scoped_secret_sql(
                secret_name=f"ducklake_s3_dest_{i}",
                scope=f"s3://{dest.bucket_name}",
                access_key=access_key,
                secret_key=secret_key,
                session_token=session_token,
                region=dest.region,
            )
            conn.execute(secret_sql)


def ensure_ducklake_bucket_exists(
    storage_config: DuckLakeStorageConfig | None = None,
    config: dict[str, str] | None = None,
) -> None:
    """Ensure the DuckLake bucket exists (local dev only).

    This is a no-op in production environments. In local dev, it creates the
    bucket if it doesn't exist.

    Args:
        storage_config: Storage config to use. If None, creates one from runtime.
        config: DuckLake config dict. If None, uses get_config().
    """
    if storage_config is None:
        storage_config = DuckLakeStorageConfig.from_runtime()

    if not storage_config.is_local:
        return

    if config is None:
        config = get_config()

    from products.data_warehouse.backend.s3 import ensure_bucket_exists

    settings = _get_django_settings()
    raw_endpoint = getattr(settings, "OBJECT_STORAGE_ENDPOINT", "") if settings else ""

    ensure_bucket_exists(
        f"s3://{config['DUCKLAKE_BUCKET'].rstrip('/')}",
        storage_config.access_key,
        storage_config.secret_key,
        raw_endpoint,
    )


def get_deltalake_storage_options(storage_config: DuckLakeStorageConfig | None = None) -> dict[str, str]:
    """Get storage options for deltalake library.

    Convenience function that creates a storage config from runtime if not provided.

    Args:
        storage_config: Storage config to use. If None, creates one from runtime.

    Returns:
        Dict of storage options to pass to deltalake.DeltaTable.
    """
    if storage_config is None:
        storage_config = DuckLakeStorageConfig.from_runtime()
    return storage_config.to_deltalake_options()


__all__ = [
    "DuckLakeStorageConfig",
    "CrossAccountDestination",
    "configure_connection",
    "configure_cross_account_connection",
    "ensure_ducklake_bucket_exists",
    "get_deltalake_storage_options",
    "normalize_endpoint",
]
