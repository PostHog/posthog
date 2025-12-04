from __future__ import annotations

import os
from typing import TypedDict
from urllib.parse import urlparse

import duckdb
import psycopg
from psycopg import sql

DEFAULTS: dict[str, str] = {
    "DUCKLAKE_CATALOG_DSN": "ducklake:postgres:dbname=ducklake_catalog host=localhost user=posthog password=posthog",
    "DUCKLAKE_DATA_BUCKET": "ducklake-dev",
    "DUCKLAKE_DATA_ENDPOINT": "http://localhost:19000",
    "DUCKLAKE_S3_ACCESS_KEY": "object_storage_root_user",
    "DUCKLAKE_S3_SECRET_KEY": "object_storage_root_password",
}


def get_config() -> dict[str, str]:
    return {key: os.environ.get(key, default) or default for key, default in DEFAULTS.items()}


def escape(value: str) -> str:
    return value.replace("'", "''")


def normalize_endpoint(raw_endpoint: str) -> tuple[str, bool]:
    value = (raw_endpoint or "").strip()
    if not value:
        value = DEFAULTS["DUCKLAKE_DATA_ENDPOINT"]

    if "://" in value:
        parsed = urlparse(value)
        endpoint = parsed.netloc or parsed.path
        use_ssl = parsed.scheme.lower() == "https"
    else:
        endpoint = value
        use_ssl = False

    endpoint = endpoint.rstrip("/") or "localhost:19000"
    return endpoint, use_ssl


def configure_connection(
    conn: duckdb.DuckDBPyConnection,
    config: dict[str, str],
    *,
    install_extension: bool,
) -> None:
    if install_extension:
        conn.sql("INSTALL ducklake")
    conn.sql("LOAD ducklake")

    endpoint, use_ssl = normalize_endpoint(config["DUCKLAKE_DATA_ENDPOINT"])
    conn.sql(f"SET s3_endpoint='{escape(endpoint)}'")
    conn.sql(f"SET s3_use_ssl={'true' if use_ssl else 'false'}")
    conn.sql(f"SET s3_access_key_id='{escape(config['DUCKLAKE_S3_ACCESS_KEY'])}'")
    conn.sql(f"SET s3_secret_access_key='{escape(config['DUCKLAKE_S3_SECRET_KEY'])}'")


def attach_catalog(
    conn: duckdb.DuckDBPyConnection,
    config: dict[str, str],
    *,
    alias: str = "ducklake_dev",
) -> None:
    if not alias.replace("_", "a").isalnum():
        raise ValueError(f"Unsupported DuckLake alias '{alias}'")

    data_path = f"s3://{config['DUCKLAKE_DATA_BUCKET'].rstrip('/')}/"
    conn.sql(f"ATTACH '{escape(config['DUCKLAKE_CATALOG_DSN'])}' AS {alias} (DATA_PATH '{escape(data_path)}')")


def run_smoke_check(conn: duckdb.DuckDBPyConnection, *, alias: str = "ducklake_dev") -> None:
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


def ensure_ducklake_catalog(config: dict[str, str]) -> None:
    params = parse_postgres_dsn(config["DUCKLAKE_CATALOG_DSN"])
    target_db = params.get("dbname")
    if not target_db:
        raise ValueError("DUCKLAKE_CATALOG_DSN must include a dbname value")

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


def initialize_ducklake(config: dict[str, str], *, alias: str = "ducklake_dev") -> bool:
    conn = duckdb.connect()
    try:
        ensure_ducklake_catalog(config)
        configure_connection(conn, config, install_extension=True)
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
    "configure_connection",
    "escape",
    "get_config",
    "ensure_ducklake_catalog",
    "initialize_ducklake",
    "normalize_endpoint",
    "parse_postgres_dsn",
    "run_smoke_check",
]
