from __future__ import annotations

import os
from typing import TYPE_CHECKING, TypedDict

import duckdb
import psycopg
from psycopg import sql

if TYPE_CHECKING:
    from posthog.ducklake.models import DuckLakeCatalog

DEFAULTS: dict[str, str] = {
    "DUCKLAKE_RDS_HOST": "localhost",
    "DUCKLAKE_RDS_PORT": "5432",
    "DUCKLAKE_RDS_DATABASE": "ducklake",
    "DUCKLAKE_RDS_USERNAME": "posthog",
    "DUCKLAKE_RDS_PASSWORD": "posthog",
    "DUCKLAKE_BUCKET": "ducklake-dev",
    "DUCKLAKE_BUCKET_REGION": "us-east-1",
    # Optional: S3 credentials for local dev (production uses IRSA)
    "DUCKLAKE_S3_ACCESS_KEY": "",
    "DUCKLAKE_S3_SECRET_KEY": "",
}


def get_config() -> dict[str, str]:
    """Get DuckLake configuration from environment variables.

    In dev mode, returns sensible localhost defaults. In production,
    requires environment variables to be set.
    """
    if is_dev_mode():
        return {key: os.environ.get(key, default) or default for key, default in DEFAULTS.items()}

    return _get_config_from_env_strict()


def get_team_config(team_id: int) -> dict[str, str]:
    """Get DuckLake configuration for a specific team from DuckLakeCatalog."""
    if is_dev_mode():
        return get_config()

    catalog = get_ducklake_catalog_for_team(team_id)
    if catalog is not None:
        config = catalog.to_public_config()
        config["DUCKLAKE_RDS_PASSWORD"] = catalog.db_password
        return config
    raise ValueError(f"No DuckLakeCatalog configured for team {team_id}")


def is_dev_mode() -> bool:
    """Check if running in development mode."""
    try:
        from posthog.settings import USE_LOCAL_SETUP

        return USE_LOCAL_SETUP
    except ImportError:
        return True


def _get_config_from_env_strict() -> dict[str, str]:
    """Get config from environment variables, raising if required vars are missing."""
    config = {}
    required_keys = {"DUCKLAKE_RDS_HOST", "DUCKLAKE_RDS_PASSWORD", "DUCKLAKE_BUCKET"}
    for key, default in DEFAULTS.items():
        value = os.environ.get(key) or ""
        if key in required_keys and not value:
            raise ValueError(f"Required environment variable {key} is not set")
        config[key] = value or default
    return config


def get_ducklake_catalog_for_team(team_id: int) -> DuckLakeCatalog | None:
    """Look up DuckLakeCatalog for a team.

    Returns None if no team-specific catalog is configured or in dev mode.
    """
    if is_dev_mode():
        return None

    from posthog.ducklake.models import DuckLakeCatalog

    try:
        return DuckLakeCatalog.objects.get(team_id=team_id)
    except DuckLakeCatalog.DoesNotExist:
        return None


def get_ducklake_connection_string(config: dict[str, str] | None = None) -> str:
    """Build the DuckLake catalog connection string from config or environment variables."""
    if config is None:
        config = get_config()

    host = config.get("DUCKLAKE_RDS_HOST")
    port = config.get("DUCKLAKE_RDS_PORT", "5432")
    database = config.get("DUCKLAKE_RDS_DATABASE", "ducklake")
    username = config.get("DUCKLAKE_RDS_USERNAME", "posthog")
    password = config.get("DUCKLAKE_RDS_PASSWORD")

    if not host or not password:
        raise ValueError("DUCKLAKE_RDS_HOST and DUCKLAKE_RDS_PASSWORD must be set")

    conn_str = f"postgres:dbname={database} host={host} port={port} user={username} password={password}"
    if not is_dev_mode():
        conn_str += " sslmode=require"
    return conn_str


def get_ducklake_data_path(config: dict[str, str] | None = None) -> str:
    """Get the DuckLake S3 data path from config or environment variables."""
    if config is None:
        config = get_config()

    bucket = config.get("DUCKLAKE_BUCKET")
    if not bucket:
        raise ValueError("DUCKLAKE_BUCKET must be set")
    return f"s3://{bucket}/"


def escape(value: str) -> str:
    return value.replace("'", "''")


def attach_catalog(
    conn: duckdb.DuckDBPyConnection,
    config: dict[str, str] | None = None,
    *,
    alias: str = "ducklake",
) -> None:
    """Attach the DuckLake catalog to the DuckDB connection.

    Args:
        conn: DuckDB connection
        config: Configuration dict (uses get_config() if None)
        alias: Catalog alias (default: "ducklake")
    """
    if config is None:
        config = get_config()

    if not alias.replace("_", "a").isalnum():
        raise ValueError(f"Unsupported DuckLake alias '{alias}'")

    catalog_uri = get_ducklake_connection_string(config)
    data_path = get_ducklake_data_path(config)
    try:
        conn.sql(f"ATTACH '{escape(catalog_uri)}' AS {alias} (TYPE ducklake, DATA_PATH '{escape(data_path)}')")
    except Exception as e:
        password = config.get("DUCKLAKE_RDS_PASSWORD", "")
        if password:
            scrubbed_msg = str(e).replace(password, "***")
            raise type(e)(scrubbed_msg) from None
        raise


def run_smoke_check(conn: duckdb.DuckDBPyConnection, *, alias: str = "ducklake") -> None:
    conn.sql(f"SHOW TABLES FROM {alias}")


def _strip_postgres_prefix(raw_dsn: str) -> str:
    for prefix in ("ducklake:postgres:", "postgres:"):
        if raw_dsn.startswith(prefix):
            return raw_dsn[len(prefix) :]
    return raw_dsn


def parse_postgres_dsn(raw_dsn: str) -> dict[str, str]:
    cleaned = _strip_postgres_prefix(raw_dsn or "")
    params: dict[str, str] = {}
    for chunk in cleaned.split():
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        params[key] = value.strip("'\"")
    return params


class PsycopgConnectionConfig(TypedDict):
    dbname: str
    host: str
    port: int
    user: str
    password: str
    autocommit: bool


def ensure_ducklake_catalog(config: dict[str, str] | None = None) -> None:
    """Ensure the DuckLake Postgres catalog database exists."""
    if config is None:
        config = get_config()

    catalog_dsn = get_ducklake_connection_string(config)
    params = parse_postgres_dsn(catalog_dsn)
    target_db = params.get("dbname")
    if not target_db:
        raise ValueError("DUCKLAKE_RDS_DATABASE must be set")

    conn_kwargs: PsycopgConnectionConfig = {
        "dbname": params.get("maintenance_db") or "postgres",
        "host": params.get("host") or "localhost",
        "port": int(params.get("port") or "5432"),
        "user": params.get("user") or "posthog",
        "password": params.get("password") or "posthog",
        "autocommit": True,
    }

    try:
        with psycopg.connect(**conn_kwargs) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
                if cur.fetchone():
                    return

                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
                owner = params.get("user")
                if owner:
                    cur.execute(
                        sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
                            sql.Identifier(target_db),
                            sql.Identifier(owner),
                        )
                    )
    except psycopg.OperationalError as exc:  # pragma: no cover - depends on PG state
        raise RuntimeError("Unable to ensure DuckLake catalog exists. Is Postgres running and accessible?") from exc


def initialize_ducklake(config: dict[str, str] | None = None, *, alias: str = "ducklake") -> bool:
    """Initialize DuckLake: ensure catalog exists, configure connection, and attach catalog."""
    if config is None:
        config = get_config()

    conn = duckdb.connect()
    try:
        ensure_ducklake_catalog(config)
        try:
            attach_catalog(conn, config, alias=alias)
            attached = True
        except duckdb.CatalogException as exc:
            if alias in str(exc):
                attached = False
            else:
                raise
        run_smoke_check(conn, alias=alias)
        return attached
    finally:
        conn.close()


__all__ = [
    "attach_catalog",
    "escape",
    "get_config",
    "get_ducklake_connection_string",
    "get_team_config",
    "get_ducklake_data_path",
    "ensure_ducklake_catalog",
    "initialize_ducklake",
    "parse_postgres_dsn",
    "is_dev_mode",
    "run_smoke_check",
]
