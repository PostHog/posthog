"""HTTP client for duckgres's billing pull API.

Duckgres meters managed-warehouse compute per (org, team, query_source, worker
size) and serves it aggregated per UTC day over the un-acked window
(`GET /api/v1/billing/usage`). Acking a watermark (`POST /api/v1/billing/ack`)
advances the server-side cursor and deletes the acked buckets, so the caller
must persist rows before acking. Wire contract: duckgres PR #893
(`docs/design/billing-pull-api.md`).

Uses the same control-plane base URL, internal-secret header, and outbound
proxy as the provisioning adapter
(`products.data_warehouse.backend.presentation.views.managed_warehouse`).
"""

import json
import datetime as dt
import dataclasses
from decimal import Decimal, InvalidOperation

from django.conf import settings

import structlog

from posthog.security.outbound_proxy import internal_requests

logger = structlog.get_logger(__name__)

SECRET_HEADER = "X-Duckgres-Internal-Secret"


class DuckgresBillingNotConfigured(Exception):
    """DUCKGRES_API_URL / DUCKGRES_INTERNAL_SECRET are not set in this environment."""


class DuckgresBillingAPIError(Exception):
    """The billing pull API returned a non-2xx response."""


@dataclasses.dataclass(frozen=True)
class UsageRow:
    """One aggregated usage row: one (org, team, query_source, worker size) on one UTC day."""

    date: dt.date
    org_id: str
    team_id: int
    query_source: str
    cpu: Decimal
    mem_gib: Decimal
    cpu_seconds: int
    memory_seconds: int


@dataclasses.dataclass(frozen=True)
class StorageRow:
    """One aggregated storage row: one (org, team) footprint-integral on one UTC day.

    `gib_seconds` is duckgres's exact decimal (integer byte-seconds / 2^30, up
    to 30 fractional digits) — it must never pass through a float.
    """

    date: dt.date
    org_id: str
    team_id: int
    gib_seconds: Decimal


@dataclasses.dataclass(frozen=True)
class UsageResponse:
    watermark_low: dt.datetime
    watermark_high: dt.datetime
    rows: list[UsageRow]
    storage_rows: list[StorageRow] = dataclasses.field(default_factory=list)


def is_configured() -> bool:
    """Whether this environment can talk to the billing pull API.

    Both routes are admin-authed, so a missing secret means every call would
    401 — treat it as unconfigured rather than hammering the control plane.
    """
    return _config() is not None


def _config() -> tuple[str, str] | None:
    """(base_url, secret) when both are set, else None."""
    base_url = getattr(settings, "DUCKGRES_API_URL", None)
    secret = getattr(settings, "DUCKGRES_INTERNAL_SECRET", None)
    if not base_url or not secret:
        return None
    return base_url, secret


def fetch_usage(timeout: int = 60) -> UsageResponse:
    """Fetch usage aggregated per key per UTC day over the un-acked window."""
    body = _request("GET", "billing/usage", timeout=timeout)

    rows: list[UsageRow] = []
    for raw in body.get("usage") or []:
        try:
            rows.append(
                UsageRow(
                    date=dt.date.fromisoformat(raw["date"]),
                    org_id=raw["org_id"],
                    team_id=int(raw["team_id"]),
                    query_source=raw["query_source"],
                    cpu=Decimal(str(raw["cpu"])),
                    mem_gib=Decimal(str(raw["mem_gib"])),
                    cpu_seconds=int(raw["cpu_seconds"]),
                    memory_seconds=int(raw["memory_seconds"]),
                )
            )
        except (KeyError, ValueError, TypeError, InvalidOperation):
            # team_id comes from posthog itself (the org's default team at
            # provision time), so an unparseable row is an upstream bug in a
            # single row — skip it rather than poisoning every poll. The
            # replace semantics re-serve the row on every pull until fixed.
            logger.warning("duckgres_usage_row_unparseable", row=raw)

    storage_rows: list[StorageRow] = []
    # Absent on pre-#913 servers; present-but-unconsumed is NOT an option once
    # this environment acks (the shared ack deletes both families).
    for raw in body.get("storage") or []:
        try:
            storage_rows.append(
                StorageRow(
                    date=dt.date.fromisoformat(raw["date"]),
                    org_id=raw["org_id"],
                    team_id=int(raw["team_id"]),
                    gib_seconds=Decimal(str(raw["gib_seconds"])),
                )
            )
        except (KeyError, ValueError, TypeError, InvalidOperation):
            logger.warning("duckgres_storage_row_unparseable", row=raw)

    return UsageResponse(
        watermark_low=_parse_rfc3339(body["watermark_low"]),
        watermark_high=_parse_rfc3339(body["watermark_high"]),
        rows=rows,
        storage_rows=storage_rows,
    )


def ack_usage(watermark_high: dt.datetime, timeout: int = 30) -> None:
    """Advance duckgres's billing cursor; duckgres deletes buckets ≤ the watermark.

    Only call after the rows covering the watermark are committed — this is
    the custody handoff. Re-acking the same watermark is a server-side no-op.
    """
    if watermark_high.tzinfo is None:
        raise ValueError("watermark_high must be timezone-aware (UTC)")
    watermark = watermark_high.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _request("POST", "billing/ack", json_body={"watermark_high": watermark}, timeout=timeout)


def _request(method: str, path: str, json_body: dict | None = None, timeout: int = 60) -> dict:
    config = _config()
    if config is None:
        raise DuckgresBillingNotConfigured(
            "DUCKGRES_API_URL and DUCKGRES_INTERNAL_SECRET must both be set to pull billing usage"
        )

    base_url, secret = config
    url = f"{base_url.rstrip('/')}/api/v1/{path}"
    headers = {SECRET_HEADER: secret}

    response = internal_requests.request(method, url, json=json_body, headers=headers, timeout=timeout)
    if response.status_code >= 400:
        raise DuckgresBillingAPIError(f"{method} {path} returned {response.status_code}: {response.text[:500]}")
    # parse_float=Decimal: storage gib_seconds carry up to ~30 fractional
    # digits of exact decimal; float64 keeps ~16 significant digits and would
    # silently corrupt them before any code sees the value.
    return json.loads(response.text, parse_float=Decimal)


def _parse_rfc3339(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.UTC)
