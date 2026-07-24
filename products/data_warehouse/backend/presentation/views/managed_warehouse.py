"""Adapter for the org-scoped managed warehouse provisioning API (duckgres).

Centralizes everything the `DataWarehouseViewSet` provisioning actions need so the
ViewSet stays a thin pass-through: org-scoped feature gating, duckgres org-URL
construction and request/error mapping, warehouse-name validation (shared by provision
and availability checks), and connection presentation.

A managed warehouse is shared by every team in an organization, so the duckgres org
identifier is the PostHog `organization_id` and the Data ops feature flag is evaluated
per organization (not per team).
"""

import re
from datetime import date
from typing import TypedDict, cast
from uuid import UUID

from django.conf import settings
from django.db import transaction

import requests as http_requests
import structlog
import posthoganalytics
from rest_framework import status
from rest_framework.response import Response

from posthog.security.outbound_proxy import internal_requests

logger = structlog.get_logger(__name__)

DATA_WAREHOUSE_SCENE_FLAG = "data-warehouse-scene"

# The Postgres database to connect to is always "ducklake"; the user-chosen warehouse
# name becomes the SNI subdomain (e.g. my-warehouse.dw.us.postwh.com) and the DNS zone
# is selected by the deployment.
MANAGED_WAREHOUSE_DATABASE = "ducklake"
_MANAGED_WAREHOUSE_DOMAINS = {
    "US": "us.postwh.com",
    "EU": "eu.postwh.com",
    "DEV": "dev.postwh.com",
}

# A warehouse name becomes a DNS-1123 label (the connection's SNI subdomain), so it must
# be lowercase alphanumerics and hyphens, starting and ending alphanumeric — no
# underscores. Mirrors duckgres's own org-id constraint.
WAREHOUSE_NAME_MIN_LENGTH = 3
WAREHOUSE_NAME_MAX_LENGTH = 63
WAREHOUSE_NAME_PATTERN = re.compile(r"^[a-z]([a-z0-9-]*[a-z0-9])?$")


class PresentedConnection(TypedDict):
    host: str
    port: int
    database: str
    username: str


def managed_warehouse_domain() -> str:
    deployment = (getattr(settings, "CLOUD_DEPLOYMENT", None) or "").upper()
    return _MANAGED_WAREHOUSE_DOMAINS.get(deployment, "test.local")


def validate_warehouse_name(name: str | None) -> str | None:
    """Return a human-readable error if `name` is not a valid warehouse name, else None."""
    if not name:
        return "database_name is required"
    if not (WAREHOUSE_NAME_MIN_LENGTH <= len(name) <= WAREHOUSE_NAME_MAX_LENGTH):
        return f"Warehouse name must be {WAREHOUSE_NAME_MIN_LENGTH}-{WAREHOUSE_NAME_MAX_LENGTH} characters"
    if not WAREHOUSE_NAME_PATTERN.match(name):
        return (
            "Warehouse name must be a DNS label: lowercase letters, numbers, and hyphens, "
            "starting and ending with a letter or number"
        )
    return None


def is_enabled(organization_id: UUID | str) -> bool:
    """Evaluate the managed-warehouse flag for the organization.

    Identity is the organization so every team in the org resolves the same value.
    """
    org_id = str(organization_id)
    try:
        return bool(
            posthoganalytics.feature_enabled(
                DATA_WAREHOUSE_SCENE_FLAG,
                org_id,
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.warning("Failed to evaluate managed warehouse feature flag", organization_id=org_id)
        return False


def _present_connection(raw: dict) -> PresentedConnection:
    """Build the public-facing connection from duckgres's raw status connection.

    duckgres returns the org's chosen warehouse name as `database`; that becomes the SNI
    subdomain of the host, and the database to connect to is always "ducklake".
    """
    warehouse_name = raw.get("database")
    host = f"{warehouse_name}.dw.{managed_warehouse_domain()}" if warehouse_name else raw.get("host", "")
    return PresentedConnection(
        host=host,
        port=getattr(settings, "DUCKGRES_PG_PORT", 5432),
        database=MANAGED_WAREHOUSE_DATABASE,
        username=raw.get("username", "root"),
    )


def _request(
    method: str,
    organization_id: UUID | str,
    path: str,
    json_body: dict | None = None,
    params: dict | None = None,
    timeout: int = 30,
    require_enabled: bool = True,
) -> Response:
    """Proxy a request to the duckgres provisioning API, gated on the org's feature flag.

    An empty path targets the org resource itself (`/api/v1/orgs/{org}`, e.g. to delete it);
    paths starting with "/" are org-scoped (`/api/v1/orgs/{org}{path}`); others are global
    API paths (`/api/v1/{path}`).

    `require_enabled` gates on the user-facing `data-warehouse-scene` flag and is the right
    default for UI-driven calls. Backend/background callers (e.g. the Dagster duckling
    backfill) must pass `require_enabled=False`: the flag is evaluated only-locally and a
    worker without the flag definition loaded would otherwise get a spurious 403 even when
    the control plane can answer.
    """
    if require_enabled and not is_enabled(organization_id):
        return Response({"error": "This feature is not enabled"}, status=status.HTTP_403_FORBIDDEN)

    base_url = getattr(settings, "DUCKGRES_API_URL", None)
    token = getattr(settings, "DUCKGRES_INTERNAL_SECRET", None)
    org_id = str(organization_id)

    if not base_url:
        logger.warning("Provisioning request rejected: DUCKGRES_API_URL not configured", organization_id=org_id)
        return Response(
            {"error": "Managed warehouse provisioning is not configured"},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )

    if path == "":
        url = f"{base_url.rstrip('/')}/api/v1/orgs/{org_id}"
    elif path.startswith("/"):
        url = f"{base_url.rstrip('/')}/api/v1/orgs/{org_id}{path}"
    else:
        url = f"{base_url.rstrip('/')}/api/v1/{path}"

    headers = {}
    if token:
        headers["X-Duckgres-Internal-Secret"] = token

    try:
        resp = internal_requests.request(method, url, json=json_body, params=params, headers=headers, timeout=timeout)
    except http_requests.Timeout:
        logger.warning("Provisioning API timeout", method=method, path=path, organization_id=org_id)
        return Response({"error": "Provisioning service timed out"}, status=status.HTTP_504_GATEWAY_TIMEOUT)
    except http_requests.ConnectionError:
        logger.warning("Provisioning API connection refused", method=method, path=path, organization_id=org_id)
        return Response({"error": "Provisioning service is unreachable"}, status=status.HTTP_502_BAD_GATEWAY)
    except Exception:
        logger.exception("Provisioning API unexpected error", method=method, path=path, organization_id=org_id)
        return Response(
            {"error": "An error occurred contacting the provisioning service"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if resp.status_code >= 400:
        logger.warning(
            "Provisioning API returned error",
            method=method,
            path=path,
            organization_id=org_id,
            status_code=resp.status_code,
            response_body=resp.text[:500],
        )
    else:
        logger.info("Provisioning API request succeeded", method=method, path=path, organization_id=org_id)

    try:
        body = resp.json()
    except ValueError:
        body = {"error": resp.text[:500]}
    return Response(body, status=resp.status_code)


def _get_project_team_row(*, organization_id: UUID | str, team_id: int) -> dict | None:
    """Fetch the org-team row Duckgres currently holds for this project, if any."""
    resp = _request("GET", organization_id, "/teams", require_enabled=False)
    if not status.is_success(resp.status_code) or not isinstance(resp.data, dict):
        raise RuntimeError("Failed to read the organization's managed warehouse team rows")
    for row in resp.data.get("teams") or []:
        if isinstance(row, dict) and _row_team_id(row) == team_id:
            return row
    return None


def _row_team_id(row: dict) -> int | None:
    """A control-plane row's team id as int, tolerating a string serialization."""
    try:
        return int(row["team_id"])
    except (KeyError, TypeError, ValueError):
        return None


def configure_project_reader(
    *, organization_id: UUID | str, team_id: int, table_suffix: str, password: str
) -> dict[str, str]:
    """Apply the project's read-only credential, creating its team row only when absent.

    The org-team row is Duckgres-owned state that also drives external-writer discovery
    (viaduck/millpond write targets) and may be hand-set (break-glass edits, legacy layouts).
    An existing row is therefore never rewritten from this path; the derived naming below is
    used only to create a row that does not exist yet.
    """
    row = _get_project_team_row(organization_id=organization_id, team_id=team_id)
    if row is None:
        team_response = _request(
            "POST",
            organization_id,
            "/teams",
            json_body={
                "team_id": team_id,
                "schema_name": f"team_{team_id}",
                "enabled": True,
                "events_table_name": f"events_{table_suffix}",
                "persons_table_name": f"persons_{table_suffix}",
                "schema_data_imports_name": f"posthog_data_imports_{table_suffix}",
            },
            require_enabled=False,
        )
        if not status.is_success(team_response.status_code):
            raise RuntimeError("Failed to register the project's managed warehouse namespaces")
    elif row.get("enabled") is not True:
        # `enabled` is an operator-facing serving hold; do not silently lift it here.
        raise RuntimeError("The project's managed warehouse team row is disabled")

    credential_response = _request(
        "PUT",
        organization_id,
        f"/teams/{team_id}/project-reader",
        json_body={"password": password},
        require_enabled=False,
    )
    if not status.is_success(credential_response.status_code) or not isinstance(credential_response.data, dict):
        raise RuntimeError("Failed to create the project's managed warehouse reader")
    username = credential_response.data.get("username")
    response_password = credential_response.data.get("password")
    if not isinstance(username, str) or not username or not isinstance(response_password, str) or not response_password:
        raise RuntimeError("Managed warehouse reader response did not include credentials")
    return {"username": username, "password": response_password}


def project_reader_namespaces(
    *, organization_id: UUID | str, team_id: int
) -> tuple[set[str], set[tuple[str, str]]] | None:
    """Return the (whole schemas, legacy posthog-schema tables) the project's reader may see.

    Mirrors the Duckgres policy derivation from the org-team row: the reader is granted the row's
    schema_name, its data-imports schema (override or `<schema>_data_imports`), the modeled-data
    schema, and `posthog.<override>` for each non-NULL legacy events/persons override — including
    overrides that spell the derived default name. None means no enabled row exists (fail closed).
    """
    row = _get_project_team_row(organization_id=organization_id, team_id=team_id)
    if row is None or row.get("enabled") is not True:
        return None
    schema_name = str(row.get("schema_name") or "")
    if not schema_name:
        return None
    imports_schema = str(row.get("schema_data_imports_name") or "") or f"{schema_name}_data_imports"
    schemas = {schema_name, imports_schema, f"shadow_{team_id}_models"}
    relations: set[tuple[str, str]] = set()
    for override_field in ("events_table_name", "persons_table_name"):
        override = row.get(override_field)
        if isinstance(override, str) and override:
            relations.add(("posthog", override))
    return schemas, relations


def provision(
    organization_id: UUID | str,
    database_name: str | None,
    team_id: int,
    schema_name: str | None,
    require_enabled: bool = True,
) -> Response:
    name_error = validate_warehouse_name(database_name)
    if name_error:
        return Response({"error": name_error}, status=status.HTTP_400_BAD_REQUEST)
    # Validate the schema name up front: the duckling backfill setup runs best-effort after the
    # provision call, so a bad name there would be swallowed — catch it before provisioning.
    schema_name_error = _validate_schema_name(schema_name)
    if schema_name_error or schema_name is None:
        return Response({"error": schema_name_error or "schema_name is required"}, status=status.HTTP_400_BAD_REQUEST)
    resp = _request(
        "POST",
        organization_id,
        "/provision",
        json_body={
            "database_name": database_name,
            # The provisioning team becomes the warehouse's first team (and its billing
            # team): duckgres creates its team row with this schema. In-product this is
            # the calling (currently active) team; in the Django admin it's the mandatory
            # team field on the provision form.
            "team_id": team_id,
            "schema_name": schema_name,
            "ducklake": {"enabled": True},
            "metadata_store": {"type": "cnpg-shard"},
            "data_store": {"type": "s3bucket"},
        },
        require_enabled=require_enabled,
    )
    if status.is_success(resp.status_code) and isinstance(resp.data, dict):
        _persist_duckgres_server(organization_id, database_name, resp.data)
        # Complete the row BEFORE registering the team: registration kicks off the
        # SQL-editor reader handshake, whose namespace grants derive from this row.
        _complete_provisioning_team_row(organization_id, team_id, schema_name, require_enabled=require_enabled)
        _register_provisioning_team(organization_id, team_id, schema_name)
        # The bucket is internal infra detail, persisted above and consumed by the
        # backfill via cp_bucket_for — not part of the UI-facing ProvisionWarehouseResponse
        # schema. Strip it so the response matches its OpenAPI contract.
        _strip_bucket_fields(resp.data)
    return resp


def _complete_provisioning_team_row(
    organization_id: UUID | str, team_id: int, schema_name: str, *, require_enabled: bool
) -> None:
    """Pin the first team's legacy table names onto the row duckgres just created.

    The provision body cannot carry them, and without them the team's SQL-editor reader is
    granted only the derived schemas no data lands in yet (see onboard_team). Best-effort:
    the warehouse is already provisioned, so a transient failure must not fail the provision —
    re-running onboarding (or the grandfather upsert) completes the row later.
    """
    legacy = _grandfathered_team_fields(team_id, schema_name)
    resp = create_team(
        organization_id,
        team_id,
        schema_name,
        events_table_name=legacy["events_table_name"],
        persons_table_name=legacy["persons_table_name"],
        schema_data_imports_name=legacy["schema_data_imports_name"],
        require_enabled=require_enabled,
    )
    if not status.is_success(resp.status_code):
        logger.warning(
            "Provisioned warehouse team row could not be completed with legacy table names",
            organization_id=str(organization_id),
            team_id=team_id,
            status_code=resp.status_code,
        )


def _strip_bucket_fields(body: dict) -> None:
    """Drop the internal bucket fields from a UI-facing response body, in place."""
    body.pop("bucket", None)
    body.pop("bucket_region", None)


def _validate_schema_name(name: str | None) -> str | None:
    """Return an error message if `name` isn't a valid duckgres schema name, else None."""
    # Keep ducklake.common (and its duckdb dependency) off the API import path.
    from posthog.ducklake.common import validate_schema_name  # noqa: PLC0415

    return validate_schema_name(name)


def team_backfill_state(team_id: int) -> dict:
    """Return the calling team's duckling backfill state for the warehouse-status response."""
    # Keep ducklake.common (and its duckdb dependency) off the API import path.
    from posthog.ducklake.common import get_team_backfill_state  # noqa: PLC0415

    return get_team_backfill_state(team_id)


def _register_provisioning_team(organization_id: UUID | str, team_id: int, schema_name: str) -> None:
    """Record the provisioning (calling) team's duckling membership and enable its backfill.

    A managed warehouse is org-scoped, but membership and backfills are per team, so provision
    registers only the provisioning team: a single `DuckgresServerTeam` row carrying its
    membership and a backfill enabled with the schema name chosen at provision (stored as the
    team's table suffix, which Dagster still reads). duckgres creates its own team row from the
    provision request itself. Other teams join later via `onboard_team`, which runs the same
    dual-write.

    Best-effort, mirroring `_persist_duckgres_server`: a failure is logged, not raised, so the
    one-time provision password is never lost to it.
    """
    # Keep ducklake.common (and its duckdb dependency) off the API import path.
    from posthog.ducklake.common import enable_team_backfill  # noqa: PLC0415

    try:
        enable_team_backfill(team_id=team_id, organization_id=organization_id, table_name=schema_name)
        _schedule_earliest_event_date_sync(team_id)
    except Exception:
        logger.exception("Failed to register provisioning team after provision", team_id=team_id)


def _persist_duckgres_server(organization_id: UUID | str, database_name: str | None, body: dict) -> None:
    """Persist the org's DuckgresServer row from a successful provision response.

    The Dagster duckling backfill connects via this row, so provisioning must leave it in
    place. The connection mirrors `_present_connection` (the SNI host + "ducklake" database);
    the password is returned only in this provision response, so it's read from `body`.

    Best-effort: a persistence failure is logged but never raised, because the provision
    password is shown to the user exactly once (here) and must not be lost to a DB hiccup —
    the row can be reconciled later from the warehouse status.
    """
    # Keep ducklake.common (and its duckdb dependency) off the API import path.
    from posthog.ducklake.common import default_bucket_region, upsert_duckgres_server_for_org  # noqa: PLC0415

    # The control plane is the single owner of the bucket name — it provisions
    # the bucket, pins the name on the Duckling CR's spec.dataStore.bucketName,
    # and returns it here. Persist it verbatim; never re-derive (the old local
    # derivation drifted from the Crossplane composition and named buckets that
    # don't exist). A response without a bucket (external data store, or a CP too
    # old to return it) leaves the column unset — upsert treats None as "leave
    # unset" — and status_for()'s self-heal fills it in on the next status read.
    bucket: str | None = body.get("bucket")
    # Region from the response too when present, so a CP outside this deployment's
    # home region isn't silently mis-recorded; the fallback is the deployment's own
    # managed-warehouse region. None when there's no bucket to region.
    bucket_region: str | None = (body.get("bucket_region") or default_bucket_region()) if bucket else None

    try:
        connection = _present_connection({"database": database_name, "username": body.get("username", "root")})
        upsert_duckgres_server_for_org(
            organization_id,
            host=connection["host"],
            port=connection["port"],
            database=connection["database"],
            username=connection["username"],
            password=body.get("password", ""),
            bucket=bucket,
            bucket_region=bucket_region,
        )
    except Exception:
        logger.exception("Failed to persist DuckgresServer after provision", organization_id=str(organization_id))


def list_teams(organization_id: UUID | str, require_enabled: bool = True) -> Response:
    """List the org's duckgres team rows (schema names, legacy table names, billing flag)."""
    return _request("GET", organization_id, "/teams", require_enabled=require_enabled)


def list_all_teams() -> Response:
    """List every duckgres team row across orgs (global internal endpoint).

    Backend-only: feeds the cp-mode sensor enumeration in posthog.ducklake.cp_teams,
    which is why the feature-flag gate is bypassed.
    """
    return _request("GET", "", "teams", require_enabled=False)


def create_team(
    organization_id: UUID | str,
    team_id: int,
    schema_name: str | None,
    *,
    enabled: bool | None = None,
    backfill_enabled: bool | None = None,
    events_table_name: str | None = None,
    persons_table_name: str | None = None,
    schema_data_imports_name: str | None = None,
    require_enabled: bool = True,
) -> Response:
    """Upsert a team row in the org's duckgres warehouse.

    duckgres answers 409 when the schema name is already used by another team in the org.
    Legacy table-name fields are only sent when set — leaving them NULL makes duckgres derive
    the layout (`<schema_name>.events`, `<schema_name>.persons`, `<schema_name>_data_imports.*`);
    grandfathered teams pass their explicit legacy names instead.
    """
    schema_error = _validate_schema_name(schema_name)
    if schema_error:
        return Response({"error": schema_error}, status=status.HTTP_400_BAD_REQUEST)
    body: dict = {"team_id": team_id, "schema_name": schema_name}
    optional_fields = {
        "enabled": enabled,
        "backfill_enabled": backfill_enabled,
        "events_table_name": events_table_name,
        "persons_table_name": persons_table_name,
        "schema_data_imports_name": schema_data_imports_name,
    }
    body.update({key: value for key, value in optional_fields.items() if value is not None})
    return _request("POST", organization_id, "/teams", json_body=body, require_enabled=require_enabled)


def update_team(
    organization_id: UUID | str,
    team_id: int,
    *,
    require_enabled: bool = True,
    **fields: object,
) -> Response:
    """Update fields on an existing duckgres team row via the admin PUT endpoint.

    Presence-aware on the duckgres side: only the fields present in the body change, so
    callers pass exactly what they want written (e.g. just ``earliest_event_date``).
    """
    return _request(
        "PUT", organization_id, f"/teams/{team_id}", json_body=dict(fields), require_enabled=require_enabled
    )


def push_team_earliest_event_date(organization_id: UUID | str, team_id: int, earliest: date | None) -> bool:
    """Best-effort mirror of a team's cached earliest event date onto its duckgres team row.

    Part of the dual-write moving per-team backfill state into the control plane: the
    Django ``DuckgresServerTeam.earliest_event_date`` (including the no-history sentinel)
    stays the read source for now, so a failure here is logged and swallowed — a later
    push (the provisioning-time task or the full-backfill sensor) converges the CP row.
    Returns True when the control plane accepted the value.
    """
    if earliest is None:
        return False
    try:
        resp = update_team(organization_id, team_id, require_enabled=False, earliest_event_date=earliest.isoformat())
    except Exception:
        logger.exception(
            "Failed to push earliest event date to duckgres",
            organization_id=str(organization_id),
            team_id=team_id,
        )
        return False
    if not status.is_success(resp.status_code):
        logger.warning(
            "Duckgres rejected earliest event date push",
            organization_id=str(organization_id),
            team_id=team_id,
            status_code=resp.status_code,
        )
        return False
    return True


def _schedule_earliest_event_date_sync(team_id: int) -> None:
    """Dispatch the earliest-event-date resolution task once the membership row commits.

    ``transaction.on_commit`` so the task never races a rollback of the row it reads (it
    runs immediately in autocommit). Best-effort: a dispatch failure is logged, not
    raised — the full-backfill sensor resolves the date lazily regardless.
    """
    # Keep the Celery task module (and its import graph) off the API import path; the
    # facade is the allowed boundary for presentation -> tasks.
    from products.data_warehouse.backend.facade.tasks import sync_team_earliest_event_date  # noqa: PLC0415

    def dispatch() -> None:
        try:
            sync_team_earliest_event_date.delay(team_id)
        except Exception:
            logger.exception("Failed to schedule earliest event date sync", team_id=team_id)

    transaction.on_commit(dispatch)


def delete_team(organization_id: UUID | str, team_id: int, require_enabled: bool = True) -> Response:
    """Delete a team row from the org's duckgres warehouse.

    duckgres answers 409 for the org's last team (the org must be deprovisioned or deleted
    instead) and reassigns the billing flag to the oldest remaining team otherwise.
    """
    return _request("DELETE", organization_id, f"/teams/{team_id}", require_enabled=require_enabled)


def onboard_team(
    organization_id: UUID | str, team_id: int, schema_name: str | None, require_enabled: bool = True
) -> Response:
    """Onboard a team onto the org's existing managed warehouse with its own schema.

    Dual-write: creates the duckgres team row (the control plane owns schema uniqueness and
    answers 409 on a conflict) and the Django DuckgresServerTeam backfill row, which Dagster
    still reads. The Django guards run first so a name the team can't use (already onboarded
    with a different name, suffix collision) is rejected before anything is written to the
    control plane — the duckgres upsert would otherwise overwrite an existing row's schema.

    Backend/ops callers (the Django admin) pass `require_enabled=False` to bypass the
    org feature-flag gate.
    """
    if require_enabled and not is_enabled(organization_id):
        return Response({"error": "This feature is not enabled"}, status=status.HTTP_403_FORBIDDEN)
    schema_error = _validate_schema_name(schema_name)
    if schema_error or schema_name is None:
        return Response({"error": schema_error or "schema_name is required"}, status=status.HTTP_400_BAD_REQUEST)

    # Keep ducklake.common (and its duckdb dependency) off the API import path.
    from posthog.ducklake.common import (  # noqa: PLC0415
        DucklingBackfillEnableError,
        check_team_backfill_enable,
        enable_team_backfill,
    )

    try:
        check_team_backfill_enable(team_id=team_id, organization_id=organization_id, table_name=schema_name)
    except DucklingBackfillEnableError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    # Pin the legacy table names the duckling DAG writes today (posthog.events_<suffix>,
    # posthog_data_imports_<suffix>): the suffix for a newly onboarded team IS its schema
    # name. A row without them describes the derived layout no data lands in yet, which
    # grants the project's SQL-editor reader nothing (the EU placeholder-row bug). Drop
    # this once the duckling DAG writes the derived <schema_name>.events layout for real.
    legacy = _grandfathered_team_fields(team_id, schema_name)
    resp = create_team(
        organization_id,
        team_id,
        schema_name,
        events_table_name=legacy["events_table_name"],
        persons_table_name=legacy["persons_table_name"],
        schema_data_imports_name=legacy["schema_data_imports_name"],
        require_enabled=require_enabled,
    )
    if resp.status_code == status.HTTP_409_CONFLICT:
        return Response(
            {"error": f"The schema name '{schema_name}' is already used by another project in this organization."},
            status=status.HTTP_409_CONFLICT,
        )
    if not status.is_success(resp.status_code):
        return resp

    try:
        suffix = enable_team_backfill(team_id=team_id, organization_id=organization_id, table_name=schema_name)
    except DucklingBackfillEnableError as exc:
        # Rare race: the guards above passed but the write lost to a concurrent onboard. The
        # duckgres upsert is idempotent, so a retry after the user picks another name is safe.
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    _schedule_earliest_event_date_sync(team_id)
    return Response({"onboarded": True, "schema_name": suffix}, status=status.HTTP_200_OK)


def _grandfathered_team_fields(team_id: int, table_suffix: str | None) -> dict:
    """Map an existing Django backfill row to an explicit duckgres team payload.

    Grandfathered teams predate the derived `<schema_name>.events` layout, so their legacy
    table names are pinned explicitly: suffixed tables when a suffix is set, the shared
    `events`/`persons` tables (what the duckling DAG writes for a NULL suffix) otherwise.
    """
    if table_suffix:
        return {
            "schema_name": table_suffix,
            "events_table_name": f"events_{table_suffix}",
            "persons_table_name": f"persons_{table_suffix}",
            "schema_data_imports_name": f"posthog_data_imports_{table_suffix}",
        }
    return {
        "schema_name": f"team_{team_id}",
        "events_table_name": "events",
        "persons_table_name": "persons",
        "schema_data_imports_name": f"posthog_data_imports_team_{team_id}",
    }


def _teams_from_response(resp: Response) -> list[dict] | None:
    """Extract the team rows from a list-teams response, or None when unusable."""
    if not status.is_success(resp.status_code):
        return None
    data = resp.data
    if isinstance(data, dict):
        data = data.get("teams")
    if not isinstance(data, list):
        return None
    return [row for row in data if isinstance(row, dict)]


def team_onboarding_state(organization_id: UUID | str, team_id: int) -> dict:
    """Resolve the calling team's duckgres onboarding state for the warehouse-status response.

    Best-effort on the control-plane side: a failed list-teams call falls back to the Django
    backfill row and never fails the status read.

    Lazy grandfather backfill: a team with a Django backfill row but no duckgres team row yet
    (onboarded before the control plane tracked teams) is pushed to duckgres here, with its
    explicit legacy table names. The push is idempotent (the control plane upserts) and
    best-effort — a failure is logged and retried on the next status read.

    Reverse heal: a duckgres team row without a Django backfill row means a dual-write lost its
    second half (provision registered the team with the control plane but the Django write
    failed, or `onboard_team`'s Django write raced). Recreate the Django row from the duckgres
    schema here so Dagster picks the team up, instead of reporting it onboarded forever with no
    backfill. Only rows without explicit legacy table names are healed — those are the ones the
    dual-write created, where schema name and table suffix are the same identifier.
    """
    # Keep ducklake.common (and its duckdb dependency) off the API import path.
    from posthog.ducklake.common import get_team_backfill_state  # noqa: PLC0415

    backfill = get_team_backfill_state(team_id)
    has_django_row = bool(backfill["has_backfill"])
    table_suffix = cast(str | None, backfill["table_suffix"])

    duckgres_team: dict | None = None
    try:
        teams = _teams_from_response(list_teams(organization_id, require_enabled=False))
        if teams is not None:
            duckgres_team = next((row for row in teams if _row_team_id(row) == team_id), None)
            if duckgres_team is None and has_django_row:
                duckgres_team = _push_grandfathered_team(organization_id, team_id, table_suffix)
            elif duckgres_team is not None and not has_django_row:
                _heal_django_backfill_row(organization_id, team_id, duckgres_team)
    except Exception:
        logger.exception(
            "Failed to resolve duckgres team onboarding state",
            organization_id=str(organization_id),
            team_id=team_id,
        )

    schema_name: str | None = None
    if duckgres_team is not None:
        schema_name = duckgres_team.get("schema_name")
    elif has_django_row:
        # Control plane unreachable but the team is onboarded Django-side: report the schema
        # its grandfather push will claim.
        schema_name = _grandfathered_team_fields(team_id, table_suffix)["schema_name"]

    return {"team_onboarded": duckgres_team is not None or has_django_row, "schema_name": schema_name}


def _push_grandfathered_team(organization_id: UUID | str, team_id: int, table_suffix: str | None) -> dict | None:
    """Push a Django-only warehouse team into duckgres. Returns the pushed row, or None on failure."""
    fields = _grandfathered_team_fields(team_id, table_suffix)
    resp = create_team(
        organization_id,
        team_id,
        fields["schema_name"],
        events_table_name=fields["events_table_name"],
        persons_table_name=fields["persons_table_name"],
        schema_data_imports_name=fields["schema_data_imports_name"],
        require_enabled=False,
    )
    if not status.is_success(resp.status_code):
        logger.warning(
            "Failed to push grandfathered team to duckgres",
            organization_id=str(organization_id),
            team_id=team_id,
            status_code=resp.status_code,
        )
        return None
    logger.info(
        "duckgres_grandfathered_team_pushed",
        organization_id=str(organization_id),
        team_id=team_id,
        schema_name=fields["schema_name"],
    )
    return {"team_id": team_id, **fields}


def _heal_django_backfill_row(organization_id: UUID | str, team_id: int, duckgres_team: dict) -> None:
    """Recreate the missing Django backfill row for a duckgres-registered team. Best-effort.

    Guarded to rows without explicit legacy table names: those came from the dual-write
    (provision or onboard), where the duckgres schema name IS the Django table suffix. Rows
    with legacy overrides originate from the grandfather push, which only runs off an existing
    Django row — a missing one there is unexpected, so it's logged rather than guessed at.
    """
    # Keep ducklake.common (and its duckdb dependency) off the API import path.
    from posthog.ducklake.common import enable_team_backfill  # noqa: PLC0415

    schema_name = duckgres_team.get("schema_name")
    has_legacy_names = any(
        duckgres_team.get(key) for key in ("events_table_name", "persons_table_name", "schema_data_imports_name")
    )
    if not schema_name or has_legacy_names:
        logger.warning(
            "Duckgres team has no Django backfill row and cannot be healed",
            organization_id=str(organization_id),
            team_id=team_id,
            has_legacy_names=has_legacy_names,
        )
        return
    try:
        enable_team_backfill(team_id=team_id, organization_id=organization_id, table_name=schema_name)
        logger.info(
            "duckgres_team_django_backfill_healed",
            organization_id=str(organization_id),
            team_id=team_id,
            schema_name=schema_name,
        )
    except Exception:
        logger.exception(
            "Failed to heal Django backfill row for duckgres team",
            organization_id=str(organization_id),
            team_id=team_id,
        )


def check_schema_name(organization_id: UUID | str, name: str | None) -> Response:
    """Check whether a schema name is free within the org's warehouse.

    Checks both the duckgres team rows and the Django backfill suffixes: a Django-only row
    (not yet lazily grandfathered into duckgres) still owns its future schema name.
    """
    schema_error = _validate_schema_name(name)
    if schema_error:
        return Response({"error": schema_error}, status=status.HTTP_400_BAD_REQUEST)

    resp = list_teams(organization_id)
    teams = _teams_from_response(resp)
    if teams is None:
        return resp

    taken = any(row.get("schema_name") == name for row in teams)
    if not taken:
        # Keep ducklake.models (via ducklake.common's import graph) off the API import path.
        from posthog.ducklake.models import DuckgresServerTeam  # noqa: PLC0415

        taken = DuckgresServerTeam.objects.filter(team__organization_id=organization_id, table_suffix=name).exists()

    return Response({"name": name, "available": not taken}, status=status.HTTP_200_OK)


def block_team_deletion(team_id: int, organization_id: UUID | str) -> str | None:
    """Remove the team from the org's duckgres warehouse ahead of a Django team deletion.

    Returns a user-facing error message when the deletion must be blocked, else None.
    Narrow coupling: orgs without a managed warehouse never trigger a control-plane call, so
    unrelated team deletions are unaffected by a duckgres outage.

    duckgres refuses to delete the org's last team (409) — the warehouse must be deprovisioned
    (or the organization deleted) first, so the Django deletion is blocked with that guidance.
    When the control plane can't confirm the deletion for a team that is warehouse-onboarded,
    the deletion is blocked with a retry error rather than silently orphaning the duckgres row.
    """
    # Keep ducklake.models off the core API import path.
    # Keep ducklake.team_state (and via it ducklake.common's duckdb dependency) off the
    # API import path.
    from posthog.ducklake import team_state  # noqa: PLC0415
    from posthog.ducklake.models import DuckgresServer  # noqa: PLC0415

    if not DuckgresServer.objects.filter(organization_id=organization_id).exists():
        return None

    resp = delete_team(organization_id, team_id, require_enabled=False)
    if status.is_success(resp.status_code) or resp.status_code == status.HTTP_404_NOT_FOUND:
        return None
    if resp.status_code == status.HTTP_409_CONFLICT:
        return (
            "This is the last project in your organization's managed warehouse. "
            "Deprovision the managed warehouse in Data ops settings, or delete the organization, "
            "before deleting this project."
        )
    if team_state.backfill_row_exists(team_id, str(organization_id)):
        return "Could not remove this project from your organization's managed warehouse. Try again in a few minutes."
    # Org has a warehouse but this team has no membership row: almost certainly not
    # onboarded, so a control-plane hiccup must not block its deletion. If a duckgres-only
    # row does exist it is orphaned here, which the control plane tolerates.
    logger.warning(
        "Proceeding with team deletion despite duckgres delete-team failure",
        organization_id=str(organization_id),
        team_id=team_id,
        status_code=resp.status_code,
    )
    return None


def deprovision(organization_id: UUID | str, require_enabled: bool = True) -> Response:
    resp = _request("POST", organization_id, "/deprovision", require_enabled=require_enabled)
    if status.is_success(resp.status_code):
        # Deprovision is not re-POSTable (Duckgres 409s once the org leaves a deprovisionable
        # state), so a failed local cleanup must converge via the retrying task, not the operator.
        try:
            _remove_direct_connection_sources(organization_id)
        except Exception:
            logger.exception("Failed to remove managed warehouse query sources", organization_id=str(organization_id))
            try:
                _schedule_remove_direct_connection_sources(organization_id)
            except Exception:
                logger.exception(
                    "Failed to schedule managed warehouse query source removal",
                    organization_id=str(organization_id),
                )
                return Response(
                    {
                        "error": "The warehouse was deprovisioned but its SQL connections could not be removed or scheduled for removal. They must be cleaned up manually."
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
    return resp


def deprovision_for_org_deletion(organization_id: UUID | str) -> None:
    """Deprovision the org's managed warehouse ahead of an organization deletion.

    Called from the organization-deletion Temporal workflow while the ``DuckgresServer``
    row still exists (the Django cascade destroys it with the org). Without this call the
    duckgres warehouse outlives the organization fully alive: external writers keep
    ingesting into it, storage keeps being metered, and its credentials stay valid — while
    the Django pointer to it is gone.

    No-op for orgs without a managed warehouse (mirrors ``block_team_deletion``'s gating,
    so unrelated org deletions never touch the control plane). Idempotent against
    duckgres: 404 (warehouse unknown to the control plane) and 409 (teardown already
    started or finished — deprovision is not re-POSTable) are treated as converged. Any
    other failure raises so the Temporal activity retries; once retries are exhausted the
    workflow logs loudly and proceeds rather than wedging the org deletion on a duckgres
    outage.
    """
    # Keep ducklake.models off the core import path.
    from posthog.ducklake.models import DuckgresServer  # noqa: PLC0415

    org_id = str(organization_id)
    if not DuckgresServer.objects.filter(organization_id=organization_id).exists():
        return

    # Backend caller: bypass the user-facing feature flag so the deletion never depends on
    # flag evaluation on the Temporal worker.
    resp = deprovision(organization_id, require_enabled=False)
    if status.is_success(resp.status_code):
        logger.info(
            "Managed warehouse deprovisioning started for organization deletion",
            organization_id=org_id,
        )
        return
    if resp.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT):
        logger.info(
            "Managed warehouse already deprovisioned or unknown to duckgres; continuing organization deletion",
            organization_id=org_id,
            status_code=resp.status_code,
        )
        return
    if resp.status_code == status.HTTP_501_NOT_IMPLEMENTED:
        # DUCKGRES_API_URL is not configured (e.g. a dev/env-var-backed DuckgresServer
        # row): there is no control plane to deprovision against.
        logger.warning(
            "Managed warehouse deprovisioning skipped: provisioning API not configured",
            organization_id=org_id,
        )
        return
    raise RuntimeError(
        f"duckgres deprovision failed with status {resp.status_code} for organization {org_id}; "
        "the org's managed warehouse must be deprovisioned before the Django cascade drops its pointer"
    )


def _remove_direct_connection_sources(organization_id: UUID | str) -> None:
    """Soft-delete the org's auto-created Postgres query connections after deprovisioning."""
    # Keep the data_warehouse/warehouse_sources stack off this adapter's import path.
    from products.data_warehouse.backend.facade.api import soft_delete_managed_warehouse_sources  # noqa: PLC0415

    soft_delete_managed_warehouse_sources(organization_id=organization_id)


def _schedule_remove_direct_connection_sources(organization_id: UUID | str) -> None:
    """Queue the retrying cleanup task when the inline soft-delete failed."""
    # Keep the Celery task stack off this adapter's import path.
    from products.data_warehouse.backend.facade.api import (  # noqa: PLC0415
        schedule_soft_delete_managed_warehouse_sources,
    )

    schedule_soft_delete_managed_warehouse_sources(organization_id=organization_id)


def ensure_direct_connection_tables(team_id: int, organization_id: UUID | str) -> None:
    """Queue discovery of the team's managed-warehouse tables for the SQL editor.

    Called from the warehouse-status read once the warehouse is `ready`. Repeated requests are
    coalesced for a short interval, while later runs re-introspect the live catalog so newly created
    project tables appear automatically.
    """
    # Keep the Celery and data-warehouse task stack off this adapter's import path.
    from products.data_warehouse.backend.facade.api import schedule_managed_warehouse_tables_reconcile  # noqa: PLC0415

    try:
        schedule_managed_warehouse_tables_reconcile(team_id=team_id, organization_id=organization_id)
    except Exception:
        logger.exception(
            "Failed to schedule managed warehouse direct connection table reconciliation",
            organization_id=str(organization_id),
            team_id=team_id,
        )


def delete_org(organization_id: UUID | str, require_enabled: bool = True) -> Response:
    """Delete the org's provisioning record once teardown has finished, freeing its warehouse name.

    `deprovision` tears the warehouse down (status goes deleting → deleted); this removes the
    now-empty org row from the control plane so its `database_name` can be reused. Deprovision
    teardown has no terminal failed state (the provisioner retries indefinitely), so callers
    should only issue this once the warehouse status reports `deleted`.
    """
    return _request("DELETE", organization_id, "", require_enabled=require_enabled)


def status_for(organization_id: UUID | str) -> Response:
    resp = _request("GET", organization_id, "/warehouse/status")
    if resp.status_code == 200 and isinstance(resp.data, dict):
        # Self-heal: the control plane is the authoritative source of the per-org
        # bucket name. If the stored DuckgresServer row disagrees — NULL (row
        # created before the CP returned it) or a stale locally-derived name — fix
        # it here so the value converges on every status read without a separate
        # backfill job. The UI reads status when viewing a warehouse, so a deploy
        # heals each org the first time its status is fetched.
        _reconcile_bucket_from_status(organization_id, resp.data)
        if isinstance(resp.data.get("connection"), dict):
            resp.data["connection"] = _present_connection(resp.data["connection"])
        # Internal infra detail — reconciled above, not part of the UI-facing
        # WarehouseStatusResponse schema. Backend callers use cp_bucket_for instead.
        _strip_bucket_fields(resp.data)
    return resp


def cp_bucket_for(organization_id: UUID | str) -> str | None:
    """Authoritative S3 bucket for the org's duckling, straight from the control plane.

    For backend/background callers (the Dagster duckling backfill), not the UI. Unlike
    `status_for` it:
      - bypasses the user-facing feature-flag gate (`require_enabled=False`), so a Dagster
        worker without the flag loaded locally doesn't get a spurious 403; and
      - returns the bucket only when the status body's own `org_id` matches the org asked
        about, so a CP bug or misrouted proxy can never hand back another tenant's bucket.

    Also reconciles the stored `DuckgresServer` row so it converges for next time. Returns
    None when the control plane is unreachable, unconfigured, or names no bucket.
    """
    resp = _request("GET", organization_id, "/warehouse/status", require_enabled=False)
    if resp.status_code != 200 or not isinstance(resp.data, dict):
        return None

    response_org = resp.data.get("org_id")
    if response_org is not None and str(response_org) != str(organization_id):
        logger.warning(
            "Refusing to use control-plane bucket: status org_id mismatch",
            requested_organization_id=str(organization_id),
            response_org_id=str(response_org),
        )
        return None

    _reconcile_bucket_from_status(organization_id, resp.data)
    return resp.data.get("bucket") or None


def _reconcile_bucket_from_status(organization_id: UUID | str, body: dict) -> None:
    """Converge DuckgresServer.bucket/bucket_region onto the control-plane-reported values.

    Best-effort and side-effect-only: a single UPDATE touching only rows where the
    bucket OR the region differs (no fetch, no create). A DB hiccup is swallowed — it
    must never fail the status read it piggybacks on.
    """
    # Defense-in-depth: the request is per-org (the URL carries the org id), but
    # only write back when the response's own org_id agrees with the one we asked
    # about. A mismatch (CP bug, misrouted proxy) must never let one tenant's
    # status overwrite another's bucket mapping — that would redirect backfill
    # reads/writes to the wrong S3 bucket.
    response_org = body.get("org_id")
    if response_org is not None and str(response_org) != str(organization_id):
        logger.warning(
            "Refusing to reconcile DuckgresServer bucket: status org_id mismatch",
            requested_organization_id=str(organization_id),
            response_org_id=str(response_org),
        )
        return

    bucket = body.get("bucket")
    if not bucket:
        # External data stores / not-yet-backfilled ducklings report no bucket —
        # nothing authoritative to copy.
        return
    # Keep ducklake.common (and its duckdb dependency) off the API import path.
    from posthog.ducklake.common import default_bucket_region  # noqa: PLC0415

    bucket_region = body.get("bucket_region") or default_bucket_region()
    try:
        from posthog.ducklake.models import DuckgresServer  # noqa: PLC0415

        # exclude rows where BOTH already match, so a correct bucket with a stale
        # region (or vice versa) is still repaired.
        updated = (
            DuckgresServer.objects.filter(organization_id=organization_id)
            .exclude(bucket=bucket, bucket_region=bucket_region)
            .update(bucket=bucket, bucket_region=bucket_region)
        )
        if updated:
            logger.info(
                "duckgres_server_bucket_reconciled_from_status",
                organization_id=str(organization_id),
                bucket=bucket,
            )
    except Exception:
        logger.exception(
            "Failed to reconcile DuckgresServer bucket from status",
            organization_id=str(organization_id),
        )


def reset_password(organization_id: UUID | str) -> Response:
    resp = _request("POST", organization_id, "/reset-password")
    if status.is_success(resp.status_code) and isinstance(resp.data, dict) and resp.data.get("password"):
        try:
            _update_direct_connection_password(organization_id, resp.data["password"])
        except Exception:
            logger.exception("Failed to update managed warehouse stored password", organization_id=str(organization_id))
            return Response(
                {"error": "The password was rotated but could not be saved. Retry the password reset."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
    return resp


def _update_direct_connection_password(organization_id: UUID | str, password: str) -> None:
    """Sync the rotated root password into the server row and query connections."""
    # Keep the data_warehouse/warehouse_sources stack off this adapter's import path.
    from products.data_warehouse.backend.facade.api import update_managed_warehouse_root_password  # noqa: PLC0415

    update_managed_warehouse_root_password(organization_id=organization_id, password=password)


def check_name(organization_id: UUID | str, name: str | None) -> Response:
    name_error = validate_warehouse_name(name)
    if name_error:
        return Response({"error": name_error}, status=status.HTTP_400_BAD_REQUEST)
    return _request("GET", organization_id, "database-name/check", params={"name": name}, timeout=10)
