"""DuckLake configuration helpers.

Two-tier config system:
- **Dev mode** (USE_LOCAL_SETUP=True): every helper returns hardcoded localhost
  defaults from the DEFAULTS / DUCKGRES_DEFAULTS dicts, optionally overridden
  by environment variables. No database rows need to exist.
- **Production**: per-org config is read from the DuckgresServer model (which holds
  both the duckgres query-server connection and the separate DuckLake catalog
  connection). The get_*_for_organization() lookups return None only when the row is
  genuinely missing; callers should treat that as an error or provision the row via
  admin.

The `get_org_config()` and `get_duckgres_config_for_org()` entry-points encapsulate
this branching so callers don't need to check the mode themselves.
"""

from __future__ import annotations

import os
import re
import logging
from typing import TYPE_CHECKING, TypedDict
from uuid import UUID

import duckdb
import psycopg
from psycopg import sql

if TYPE_CHECKING:
    from posthog.ducklake.models import DuckgresServer

    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


DUCKLAKE_CATALOG_RESET_ENV_VAR = "POSTHOG_ALLOW_DUCKLAKE_CATALOG_RESET"

# The duckgres schema prefix the data-modeling shadow materialization writes models into.
DATA_MODELING_DUCKGRES_SHADOW_SCHEMA_PREFIX = "shadow"

logger = logging.getLogger(__name__)

# Managed-warehouse buckets live in the deployment's home region: us-east-1 for
# PostHog Cloud US, eu-central-1 for PostHog Cloud EU.
_BUCKET_REGION_BY_CLOUD_DEPLOYMENT: dict[str, str] = {
    "US": "us-east-1",
    "EU": "eu-central-1",
}


def default_bucket_region() -> str:
    """Deployment-default S3 region for managed-warehouse buckets.

    Prefers the CLOUD_DEPLOYMENT Django setting, falling back to the same-named
    environment variable so CLI tools work without Django configured. us-east-1
    remains the default for US, dev, and self-hosted setups.
    """
    try:
        from django.conf import settings

        deployment = getattr(settings, "CLOUD_DEPLOYMENT", None)
    except Exception:
        deployment = os.environ.get("CLOUD_DEPLOYMENT")
    return _BUCKET_REGION_BY_CLOUD_DEPLOYMENT.get((deployment or "").upper(), "us-east-1")


DEFAULTS: dict[str, str] = {
    "DUCKLAKE_RDS_HOST": "localhost",
    "DUCKLAKE_RDS_PORT": "5432",
    "DUCKLAKE_RDS_DATABASE": "ducklake",
    "DUCKLAKE_RDS_USERNAME": "posthog",
    "DUCKLAKE_RDS_PASSWORD": "posthog",
    "DUCKLAKE_BUCKET": "ducklake-dev",
    # Frozen at import time: depends on the CLOUD_DEPLOYMENT env var being set before
    # process start (override_settings cannot affect it).
    "DUCKLAKE_BUCKET_REGION": default_bucket_region(),
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


def _server_to_catalog_config(server: DuckgresServer) -> dict[str, str]:
    config = server.to_catalog_public_config()
    config["DUCKLAKE_RDS_PASSWORD"] = server.catalog_password or ""
    return config


def get_org_config(organization_id: str) -> dict[str, str]:
    """Get DuckLake catalog configuration for an organization from DuckgresServer."""
    if is_dev_mode():
        return get_config()

    server = get_duckgres_server_for_organization(organization_id)
    if server is not None:
        return _server_to_catalog_config(server)
    raise ValueError(f"No DuckgresServer configured for organization {organization_id}")


def is_dev_mode() -> bool:
    """Check if running in development mode."""
    try:
        from posthog.settings import USE_LOCAL_SETUP

        return USE_LOCAL_SETUP
    except ImportError:
        return True


def is_ducklake_catalog_reset_allowed() -> bool:
    """Allow destructive catalog resets only when local startup opted in explicitly."""
    return is_dev_mode() and os.getenv(DUCKLAKE_CATALOG_RESET_ENV_VAR) == "1"


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


def _get_org_id_for_team(team_id: int) -> str:
    """Resolve organization_id from team_id. Used by callers that only have team_id."""
    from posthog.models import Team

    team = Team.objects.only("organization_id").get(id=team_id)
    return str(team.organization_id)


def get_duckgres_server_by_team_org(team_id: int) -> DuckgresServer | None:
    """Look up DuckgresServer via team_id → organization_id.

    Convenience wrapper for callers that have team_id but server is org-scoped.
    """
    if is_dev_mode():
        return None
    org_id = _get_org_id_for_team(team_id)
    return get_duckgres_server_for_organization(org_id)


DUCKGRES_DEFAULTS: dict[str, str] = {
    "DUCKGRES_HOST": "localhost",
    "DUCKGRES_PORT": "5432",
    "DUCKGRES_FLIGHT_PORT": "8815",
    "DUCKGRES_DATABASE": "ducklake",
    "DUCKGRES_USERNAME": "posthog",
    "DUCKGRES_PASSWORD": "posthog",
}


def _server_to_config(server: DuckgresServer) -> dict[str, str]:
    return {
        "DUCKGRES_HOST": server.host,
        "DUCKGRES_PORT": str(server.port),
        "DUCKGRES_FLIGHT_PORT": str(server.flight_port),
        "DUCKGRES_DATABASE": server.database,
        "DUCKGRES_USERNAME": server.username,
        "DUCKGRES_PASSWORD": server.password,
    }


def _duckgres_dev_config() -> dict[str, str]:
    return {key: os.environ.get(key, default) or default for key, default in DUCKGRES_DEFAULTS.items()}


def get_duckgres_config_for_org(organization_id: str) -> dict[str, str]:
    """Get duckgres connection config for an organization."""
    if is_dev_mode():
        return _duckgres_dev_config()

    server = get_duckgres_server_for_organization(organization_id)
    if server is not None:
        return _server_to_config(server)
    raise ValueError(f"No DuckgresServer configured for organization {organization_id}")


def get_duckgres_server_for_organization(organization_id: str) -> DuckgresServer | None:
    """Look up DuckgresServer for an organization."""
    if is_dev_mode():
        return None

    from posthog.ducklake.models import DuckgresServer

    try:
        return DuckgresServer.objects.get(organization_id=organization_id)
    except DuckgresServer.DoesNotExist:
        return None


def upsert_duckgres_server_for_org(
    organization_id: str | UUID,
    *,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    bucket: str | None = None,
    bucket_region: str | None = None,
) -> DuckgresServer:
    """Create or update the org's DuckgresServer connection row.

    Called at managed-warehouse provision time so the org is immediately backfill-ready:
    the Dagster duckling backfill resolves both its connection and its S3 bucket from this
    row. Idempotent — re-provisioning updates the existing row. The bucket is persisted here
    so the backfill reads the authoritative name rather than re-deriving it at read time.
    """
    from posthog.ducklake.models import DuckgresServer

    defaults: dict[str, object] = {
        "host": host,
        "port": port,
        "database": database,
        "username": username,
        "password": password,
    }
    if bucket is not None:
        defaults["bucket"] = bucket
    if bucket_region is not None:
        defaults["bucket_region"] = bucket_region

    server, _ = DuckgresServer.objects.update_or_create(
        organization_id=organization_id,
        defaults=defaults,
    )
    return server


# Managed-warehouse S3 bucket naming. The duckgres control plane is the single owner of
# the per-org bucket name: it names the bucket, pins it on the Duckling CR's
# spec.dataStore.bucketName, and returns it from the provision / warehouse-status API.
# Production code reads it from there (persisted on DuckgresServer.bucket, self-healed from
# warehouse status) — it is never re-derived, because a local re-derivation drifted from the
# Crossplane composition (UUID hyphen-compaction + the mw- env suffix) and named buckets
# that don't exist. The region follows the cloud deployment: each managed warehouse
# lives in its deployment's home region (see default_bucket_region).
# Frozen at import time: depends on the CLOUD_DEPLOYMENT env var being set before
# process start (override_settings cannot affect it).
DUCKGRES_BUCKET_REGION = default_bucket_region()


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


def _get_maintenance_conn_kwargs(config: dict[str, str]) -> tuple[PsycopgConnectionConfig, str]:
    """Build psycopg connection kwargs targeting the maintenance DB and return the target DB name."""
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
    return conn_kwargs, target_db


def ensure_ducklake_catalog(config: dict[str, str] | None = None) -> None:
    """Ensure the DuckLake Postgres catalog database exists."""
    if config is None:
        config = get_config()

    conn_kwargs, target_db = _get_maintenance_conn_kwargs(config)

    try:
        with psycopg.connect(**conn_kwargs) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
                if cur.fetchone():
                    return

                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
                owner = conn_kwargs.get("user")
                if owner:
                    cur.execute(
                        sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
                            sql.Identifier(target_db),
                            sql.Identifier(owner),
                        )
                    )
    except psycopg.OperationalError as exc:  # pragma: no cover - depends on PG state
        raise RuntimeError("Unable to ensure DuckLake catalog exists. Is Postgres running and accessible?") from exc


_VERSION_MISMATCH_PATTERNS = (
    "ducklake catalog version",
    "ducklake version",
    "only ducklake versions",
)


def is_version_mismatch(exc: Exception) -> bool:
    """Check if an exception is a DuckLake catalog version mismatch."""
    msg = str(exc).lower()
    return any(pattern in msg for pattern in _VERSION_MISMATCH_PATTERNS)


def reset_ducklake_catalog(config: dict[str, str] | None = None) -> None:
    """Drop and recreate the DuckLake catalog database. Dev mode only."""
    if not is_dev_mode():
        raise RuntimeError("reset_ducklake_catalog is only allowed in dev mode")
    if not is_ducklake_catalog_reset_allowed():
        raise RuntimeError(f"DuckLake catalog reset requires local dev opt-in via {DUCKLAKE_CATALOG_RESET_ENV_VAR}=1")

    if config is None:
        config = get_config()

    conn_kwargs, target_db = _get_maintenance_conn_kwargs(config)

    with psycopg.connect(**conn_kwargs) as conn:
        with conn.cursor() as cur:
            # Terminate existing connections so DROP succeeds
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (target_db,),
            )
            cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(target_db)))
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
            owner = conn_kwargs.get("user")
            if owner:
                cur.execute(
                    sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
                        sql.Identifier(target_db),
                        sql.Identifier(owner),
                    )
                )


def initialize_ducklake(config: dict[str, str] | None = None, *, alias: str = "ducklake") -> bool:
    """Initialize DuckLake: ensure catalog exists, configure connection, and attach catalog.

    In dev mode, automatically resets the catalog database on version mismatch.
    """
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
        except (duckdb.NotImplementedException, duckdb.InvalidInputException) as exc:
            if not is_dev_mode():
                raise
            if not is_version_mismatch(exc):
                raise
            if not is_ducklake_catalog_reset_allowed():
                raise RuntimeError(
                    "DuckLake catalog reset is disabled. "
                    f"Set {DUCKLAKE_CATALOG_RESET_ENV_VAR}=1 to allow local catalog recreation."
                ) from exc
            logger.warning("DuckLake version mismatch detected, resetting catalog: %s", exc)
            conn.close()
            reset_ducklake_catalog(config)
            conn = duckdb.connect()
            attach_catalog(conn, config, alias=alias)
            attached = True
        run_smoke_check(conn, alias=alias)
        return attached
    finally:
        conn.close()


_IDENTIFIER_SANITIZE_RE = re.compile(r"[^0-9a-zA-Z]+")


def sanitize_ducklake_identifier(raw: str, *, default_prefix: str) -> str:
    """Normalize identifiers so they are safe for DuckDB (lowercase alnum + underscores).

    Non-alphanumeric runs are collapsed into a single underscore.
    If the result is empty, ``default_prefix`` is used as the identifier.
    If the result starts with a digit, ``default_prefix`` is prepended.
    Truncated to 63 characters (DuckDB identifier limit).
    """
    cleaned = _IDENTIFIER_SANITIZE_RE.sub("_", (raw or "").strip()).strip("_").lower()
    if not cleaned:
        cleaned = default_prefix
    if cleaned[0].isdigit():
        cleaned = f"{default_prefix}_{cleaned}"
    return cleaned[:63]


def validate_duckgres_identifier(identifier: str) -> None:
    """Fail-closed check that an identifier is safe for SQL interpolation.

    Only alphanumeric characters and underscores are allowed. Mirrors the
    events/persons duckling DAG's ``_validate_identifier`` so a user-supplied
    ``DuckgresServerTeam.table_suffix`` is validated identically wherever it is
    interpolated into DuckDB DDL.
    """
    if not identifier or not identifier.replace("_", "").isalnum():
        raise ValueError(f"Invalid SQL identifier: {identifier!r}")


def duckgres_data_imports_schema(team_id: int) -> str:
    """Resolve the duckgres schema the v3 data-import sink writes a team into.

    A DuckgresServer is org-scoped and hosts many teams, so each team needs its
    own schema. Historically that was ``posthog_data_imports_team_{team_id}``.
    When a team sets ``DuckgresServerTeam.table_suffix`` (the same field that
    governs its events/persons tables), the data-import schema uses that suffix
    so one user-chosen identifier names all of a team's warehouse tables.

    Backward-compatible: a NULL/empty suffix keeps the team-id schema, so
    existing teams are unaffected until a suffix is explicitly set.

    NOTE: a suffix CHANGE moves the schema and orphans the old one — callers
    that have already written a team's tables must trigger a re-prime (handled
    by the backfill state machine), not silently switch.
    """
    from posthog.ducklake.models import DuckgresServerTeam

    suffix = DuckgresServerTeam.objects.filter(team_id=team_id).values_list("table_suffix", flat=True).first()
    if not suffix:
        return f"posthog_data_imports_team_{team_id}"
    validate_duckgres_identifier(suffix)
    return f"posthog_data_imports_{suffix}"


def duckgres_data_imports_table_name(schema: ExternalDataSchema) -> str:
    """Resolve the duckgres table name for a data-import schema (copy workflow writer,
    DuckLake read binding).

    Delegates to the shared product naming so the copy workflow, v3 sink, and
    readers stay byte-identical. The shared function preserves the deployed
    copy/read names, avoiding a cutover window where readers point at a new
    table before any sink batch has created it.
    """
    # noqa comment applies to the deferred import below: posthog.ducklake is
    # imported by the product at runtime, so a module-level facade import here
    # would be circular.
    from products.warehouse_sources.backend.facade.api import (  # noqa: PLC0415 — breaks core<->product facade import cycle
        duckgres_sink_table_name,
    )

    return duckgres_sink_table_name(schema.source.source_type, schema.source.prefix, schema.normalized_name)


def duckgres_data_modeling_schema(team_id: int) -> str:
    """Resolve the duckgres schema the data-modeling shadow materialization writes a team's models into."""
    return f"{DATA_MODELING_DUCKGRES_SHADOW_SCHEMA_PREFIX}_{team_id}_models"


TABLE_SUFFIX_MAX_LENGTH = 63
# The table name the user supplies is used verbatim as the suffix in `events_<suffix>` /
# `persons_<suffix>`, so it must already be a safe SQL identifier — lowercase letters,
# numbers, and underscores. We validate rather than silently rewrite, so what the user
# types is exactly what they get.
TABLE_SUFFIX_PATTERN = re.compile(r"^[a-z0-9_]+$")


def validate_table_suffix(name: str | None) -> str | None:
    """Return a human-readable error if `name` isn't a valid table suffix, else None."""
    if not name:
        return "table_name is required"
    if len(name) > TABLE_SUFFIX_MAX_LENGTH:
        return f"Table name must be at most {TABLE_SUFFIX_MAX_LENGTH} characters"
    if not TABLE_SUFFIX_PATTERN.match(name):
        return "Table name must use only lowercase letters, numbers, and underscores"
    return None


class DucklingBackfillEnableError(Exception):
    """Raised when a team's warehouse backfill cannot be enabled (no server, name collision)."""


def enable_team_backfill(*, team_id: int, organization_id: str | UUID, table_name: str) -> str:
    """Enable a team's warehouse backfill with a dedicated set of per-environment tables.

    The user-supplied ``table_name`` is used verbatim as the table suffix (validated, not
    rewritten). Records the team↔duckling membership and the backfill suffix on a single
    DuckgresServerTeam row so the Dagster backfill writes to ``events_<suffix>`` /
    ``persons_<suffix>`` instead of the shared tables.

    **Write-once.** The suffix is fixed when the backfill is first created and cannot be changed
    afterward — including switching a legacy NULL suffix (shared tables) to a real name. Changing
    it would make the Dagster job write to a different table and split the team's existing data
    across two tables. Re-calling with the team's current name is an idempotent no-op.

    The org must already have a provisioned DuckgresServer, the name must be a valid identifier,
    and the suffix must be unique among the org's environments. Returns the suffix, or raises
    DucklingBackfillEnableError with a user-facing message.
    """
    from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam

    error = validate_table_suffix(table_name)
    if error:
        raise DucklingBackfillEnableError(error)
    suffix = table_name

    try:
        server = DuckgresServer.objects.get(organization_id=organization_id)
    except DuckgresServer.DoesNotExist:
        raise DucklingBackfillEnableError(
            "No managed warehouse is provisioned for this organization. Provision one first."
        )

    existing = DuckgresServerTeam.objects.filter(team_id=team_id).first()
    if existing is not None:
        if existing.table_suffix == suffix:
            # Same name — already set up; idempotent no-op.
            return suffix
        current = f"events_{existing.table_suffix}" if existing.table_suffix else "the shared tables"
        raise DucklingBackfillEnableError(
            f"This project already writes to {current}, and its warehouse table can't be changed — "
            "that would split its existing data across two tables."
        )

    collision = (
        DuckgresServerTeam.objects.filter(team__organization_id=organization_id, table_suffix=suffix)
        .exclude(team_id=team_id)
        .exists()
    )
    if collision:
        raise DucklingBackfillEnableError(
            f"The table name '{suffix}' is already used by another environment in this organization."
        )

    DuckgresServerTeam.objects.create(server=server, team_id=team_id, backfill_enabled=True, table_suffix=suffix)
    return suffix


def get_team_backfill_state(team_id: int) -> dict[str, object]:
    """Return the team's duckling backfill state for the warehouse-status UI.

    ``has_backfill`` distinguishes a team that has never been set up (no row → the enable form is
    safe to show) from one already backfilling (a row exists → show read-only, since the table is
    immutable). ``table_suffix`` is None for legacy teams still on the shared tables.
    """
    from posthog.ducklake.models import DuckgresServerTeam

    backfill = DuckgresServerTeam.objects.filter(team_id=team_id).values("table_suffix").first()
    if backfill is None:
        return {"has_backfill": False, "table_suffix": None}
    return {"has_backfill": True, "table_suffix": backfill["table_suffix"]}


__all__ = [
    "DucklingBackfillEnableError",
    "attach_catalog",
    "default_bucket_region",
    "duckgres_data_imports_schema",
    "duckgres_data_imports_table_name",
    "duckgres_data_modeling_schema",
    "enable_team_backfill",
    "escape",
    "get_config",
    "get_ducklake_connection_string",
    "get_ducklake_data_path",
    "get_duckgres_config_for_org",
    "get_duckgres_server_by_team_org",
    "get_duckgres_server_for_organization",
    "get_org_config",
    "ensure_ducklake_catalog",
    "initialize_ducklake",
    "is_ducklake_catalog_reset_allowed",
    "is_version_mismatch",
    "parse_postgres_dsn",
    "is_dev_mode",
    "get_team_backfill_state",
    "reset_ducklake_catalog",
    "run_smoke_check",
    "sanitize_ducklake_identifier",
    "validate_duckgres_identifier",
    "validate_table_suffix",
]
