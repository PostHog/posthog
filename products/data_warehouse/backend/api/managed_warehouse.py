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
) -> Response:
    """Proxy a request to the duckgres provisioning API, gated on the org's feature flag.

    Paths starting with "/" are org-scoped (`/api/v1/orgs/{org}{path}`); others are global
    API paths (`/api/v1/{path}`).
    """
    if not is_enabled(organization_id):
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


def provision(organization_id: UUID | str, database_name: str | None) -> Response:
    name_error = validate_warehouse_name(database_name)
    if name_error:
        return Response({"error": name_error}, status=status.HTTP_400_BAD_REQUEST)
    return _request(
        "POST",
        organization_id,
        "/provision",
        json_body={
            "database_name": database_name,
            "ducklake": {"enabled": True},
            "metadata_store": {"type": "cnpg-shard"},
            "data_store": {"type": "s3bucket"},
        },
    )


def deprovision(organization_id: UUID | str) -> Response:
    return _request("POST", organization_id, "/deprovision")


def status_for(organization_id: UUID | str) -> Response:
    resp = _request("GET", organization_id, "/warehouse/status")
    if resp.status_code == 200 and isinstance(resp.data, dict) and isinstance(resp.data.get("connection"), dict):
        resp.data["connection"] = _present_connection(resp.data["connection"])
    return resp


def reset_password(organization_id: UUID | str) -> Response:
    return _request("POST", organization_id, "/reset-password")


def check_name(organization_id: UUID | str, name: str | None) -> Response:
    name_error = validate_warehouse_name(name)
    if name_error:
        return Response({"error": name_error}, status=status.HTTP_400_BAD_REQUEST)
    return _request("GET", organization_id, "database-name/check", params={"name": name}, timeout=10)
