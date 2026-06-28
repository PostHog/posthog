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
from typing import TypedDict
from uuid import UUID

from django.conf import settings

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

    Paths starting with "/" are org-scoped (`/api/v1/orgs/{org}{path}`); others are global
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

    if path.startswith("/"):
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


def provision(
    organization_id: UUID | str,
    database_name: str | None,
    team_id: int,
    table_name: str | None,
    require_enabled: bool = True,
) -> Response:
    name_error = validate_warehouse_name(database_name)
    if name_error:
        return Response({"error": name_error}, status=status.HTTP_400_BAD_REQUEST)
    # Validate the table name up front: the duckling backfill setup runs best-effort after the
    # provision call, so a bad name there would be swallowed — catch it before provisioning.
    table_name_error = _validate_table_name(table_name)
    if table_name_error or table_name is None:
        return Response({"error": table_name_error or "table_name is required"}, status=status.HTTP_400_BAD_REQUEST)
    resp = _request(
        "POST",
        organization_id,
        "/provision",
        json_body={
            "database_name": database_name,
            "ducklake": {"enabled": True},
            "metadata_store": {"type": "cnpg-shard"},
            "data_store": {"type": "s3bucket"},
        },
        require_enabled=require_enabled,
    )
    if status.is_success(resp.status_code) and isinstance(resp.data, dict):
        _persist_duckgres_server(organization_id, database_name, resp.data)
        _register_provisioning_team(organization_id, team_id, table_name)
        # The bucket is internal infra detail, persisted above and consumed by the
        # backfill via cp_bucket_for — not part of the UI-facing ProvisionWarehouseResponse
        # schema. Strip it so the response matches its OpenAPI contract.
        _strip_bucket_fields(resp.data)
    return resp


def _strip_bucket_fields(body: dict) -> None:
    """Drop the internal bucket fields from a UI-facing response body, in place."""
    body.pop("bucket", None)
    body.pop("bucket_region", None)


def _validate_table_name(name: str | None) -> str | None:
    """Return an error message if `name` isn't a valid events/persons table suffix, else None."""
    # Keep ducklake.common (and its duckdb dependency) off the API import path.
    from posthog.ducklake.common import validate_table_suffix  # noqa: PLC0415

    return validate_table_suffix(name)


def team_backfill_state(team_id: int) -> dict:
    """Return the calling team's duckling backfill state for the warehouse-status response."""
    # Keep ducklake.common (and its duckdb dependency) off the API import path.
    from posthog.ducklake.common import get_team_backfill_state  # noqa: PLC0415

    return get_team_backfill_state(team_id)


def _register_provisioning_team(organization_id: UUID | str, team_id: int, table_name: str) -> None:
    """Record the provisioning (calling) team's duckling membership and enable its backfill.

    A managed warehouse is org-scoped, but membership and backfills are per team, so provision
    registers only the provisioning team: a single `DuckgresServerTeam` row carrying its
    membership and a backfill enabled with the per-environment table name the admin chose at
    provision — so a newly provisioned org writes to its own `events_<suffix>` tables. Other teams
    join later via `enable_backfill`, which runs the same path.

    Best-effort, mirroring `_persist_duckgres_server`: a failure is logged, not raised, so the
    one-time provision password is never lost to it.
    """
    # Keep ducklake.common (and its duckdb dependency) off the API import path.
    from posthog.ducklake.common import enable_team_backfill  # noqa: PLC0415

    try:
        enable_team_backfill(team_id=team_id, organization_id=organization_id, table_name=table_name)
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
    from posthog.ducklake.common import upsert_duckgres_server_for_org  # noqa: PLC0415

    # The control plane is the single owner of the bucket name — it provisions
    # the bucket, pins the name on the Duckling CR's spec.dataStore.bucketName,
    # and returns it here. Persist it verbatim; never re-derive (the old local
    # derivation drifted from the Crossplane composition and named buckets that
    # don't exist). A response without a bucket (external data store, or a CP too
    # old to return it) leaves the column unset — upsert treats None as "leave
    # unset" — and status_for()'s self-heal fills it in on the next status read.
    bucket: str | None = body.get("bucket")
    # Region from the response too when present, so a future CP outside us-east-1
    # isn't silently mis-recorded; None when there's no bucket to region.
    bucket_region: str | None = (body.get("bucket_region") or "us-east-1") if bucket else None

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


def enable_backfill(
    organization_id: UUID | str, team_id: int, table_name: str | None, require_enabled: bool = True
) -> Response:
    """Enable warehouse backfill for a team's environment with dedicated per-environment tables.

    Per-team (not org-wide): persists the per-environment table suffix and team↔duckling
    membership on the team's DuckgresServerTeam. Gated on the org's feature flag so
    a team can't enable a backfill for an org that isn't entitled to the managed warehouse;
    backend/ops callers (the Django admin) pass `require_enabled=False` to bypass that gate.
    """
    if require_enabled and not is_enabled(organization_id):
        return Response({"error": "This feature is not enabled"}, status=status.HTTP_403_FORBIDDEN)
    table_name_error = _validate_table_name(table_name)
    if table_name_error or table_name is None:
        return Response({"error": table_name_error or "table_name is required"}, status=status.HTTP_400_BAD_REQUEST)

    # Keep ducklake.common (and its duckdb dependency) off the API import path.
    from posthog.ducklake.common import DucklingBackfillEnableError, enable_team_backfill  # noqa: PLC0415

    try:
        suffix = enable_team_backfill(
            team_id=team_id,
            organization_id=organization_id,
            table_name=table_name,
        )
    except DucklingBackfillEnableError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({"enabled": True, "table_suffix": suffix}, status=status.HTTP_200_OK)


def deprovision(organization_id: UUID | str, require_enabled: bool = True) -> Response:
    return _request("POST", organization_id, "/deprovision", require_enabled=require_enabled)


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
    bucket_region = body.get("bucket_region") or "us-east-1"
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
    return _request("POST", organization_id, "/reset-password")


def check_name(organization_id: UUID | str, name: str | None) -> Response:
    name_error = validate_warehouse_name(name)
    if name_error:
        return Response({"error": name_error}, status=status.HTTP_400_BAD_REQUEST)
    return _request("GET", organization_id, "database-name/check", params={"name": name}, timeout=10)
