import uuid
import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from django.conf import settings

import httpx

from posthog.dataclasses import frozen

INTERNAL_API_TIMEOUT_SECONDS = 5.0
REPORTED_SPEND_TIMEOUT_SECONDS = 2.0
USAGE_REPORT_TIMEOUT_SECONDS = 35.0
BILLING_USAGE_TIMEOUT_SECONDS = 30.0
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
INTERNAL_ACTOR_HEADER = "X-Internal-Actor"
# Ledger provenance tag (meta.source): admin-originated vs the billing path's
# "billing". The acting human is audited in ActivityLog, not here.
ADMIN_ACTOR = "posthog-admin"
TASKS_COMPUTE_ACTOR = "tasks-compute"


class AIGatewayInternalError(Exception):
    """An ai-gateway internal admin API call failed."""


class AIGatewayNotConfigured(AIGatewayInternalError):
    """AI_GATEWAY_INTERNAL_URL / AI_GATEWAY_INTERNAL_TOKEN are not set."""


class AIGatewayRouteNotFound(AIGatewayInternalError):
    """The gateway answered 404, because it does not serve the route yet."""


@dataclasses.dataclass(frozen=True)
class LedgerEntry:
    when: str
    kind: str
    source: str
    destination: str
    amount: str
    reference: str


@dataclasses.dataclass(frozen=True)
class Wallet:
    team_id: int
    # known=False is a real team with no gateway account yet; has_ledger=False
    # is a deploy without the ledger backend wired (e.g. dev) — balance is None
    # in both cases.
    known: bool
    has_ledger: bool
    balance: str | None
    recent: list[LedgerEntry]


@dataclasses.dataclass(frozen=True)
class CreditResult:
    team_id: int
    entry_id: str
    amount_usd: str
    balance_usd: str
    duplicate: bool


@dataclasses.dataclass(frozen=True)
class ReportedSpendResponse:
    status_code: int
    body: dict[str, Any] | None
    text: str


def _config() -> tuple[str, str]:
    url = (settings.AI_GATEWAY_INTERNAL_URL or "").rstrip("/")
    token = settings.AI_GATEWAY_INTERNAL_TOKEN or ""
    if not url or not token:
        raise AIGatewayNotConfigured("AI_GATEWAY_INTERNAL_URL and AI_GATEWAY_INTERNAL_TOKEN must be set")
    return url, token


def _auth_headers(token: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if extra:
        headers.update(extra)
    return headers


def get_wallet(team_id: int) -> Wallet:
    url, token = _config()
    try:
        # trust_env=False keeps the in-cluster call off the egress proxy.
        response = httpx.get(
            f"{url}/internal/admin/api/teams/{team_id}",
            headers=_auth_headers(token),
            timeout=INTERNAL_API_TIMEOUT_SECONDS,
            trust_env=False,
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AIGatewayInternalError(f"wallet read failed: {exc}") from exc

    wallet = data.get("wallet") or {}
    recent = [
        LedgerEntry(
            when=row.get("when", ""),
            kind=row.get("kind", ""),
            source=row.get("source", ""),
            destination=row.get("destination", ""),
            amount=row.get("amount", ""),
            reference=row.get("reference", ""),
        )
        for row in data.get("recent") or []
    ]
    return Wallet(
        team_id=int(data.get("team_id", team_id)),
        known=bool(data.get("known", False)),
        has_ledger=bool(wallet.get("has_ledger", False)),
        balance=wallet.get("balance"),
        recent=recent,
    )


def add_credit(team_id: int, org_id: str, amount_usd: str, reason: str, idempotency_key: str) -> CreditResult:
    # Credits the organization balance that all of its teams spend from.
    url, token = _config()
    try:
        response = httpx.post(
            f"{url}/internal/accounts/{org_id}/credits",
            headers=_auth_headers(token, {IDEMPOTENCY_KEY_HEADER: idempotency_key, INTERNAL_ACTOR_HEADER: ADMIN_ACTOR}),
            json={"amount_usd": amount_usd, "reason": reason},
            timeout=INTERNAL_API_TIMEOUT_SECONDS,
            trust_env=False,
        )
    except httpx.HTTPError as exc:
        raise AIGatewayInternalError(f"credit request failed: {exc}") from exc

    if response.status_code >= 400:
        raise AIGatewayInternalError(_error_detail(response))

    try:
        data = response.json()
    except ValueError as exc:
        raise AIGatewayInternalError(f"credit response was not valid JSON: {exc}") from exc
    # A 2xx with a partial body would otherwise coerce to empty strings and surface
    # as "Added $ … New balance: $." in the admin. balance_usd may legitimately be
    # "0", so presence-check it rather than truthiness.
    if not data.get("entry_id") or data.get("balance_usd") is None:
        raise AIGatewayInternalError("credit response missing required fields (entry_id/balance_usd)")
    return CreditResult(
        team_id=int(data.get("team_id", team_id)),
        entry_id=data.get("entry_id", ""),
        amount_usd=data.get("amount_usd", ""),
        balance_usd=data.get("balance_usd", ""),
        duplicate=bool(data.get("duplicate", False)),
    )


def report_spend(wallet_team_id: int, body: dict[str, Any]) -> ReportedSpendResponse:
    url, token = _config()
    response = httpx.post(
        f"{url}/internal/teams/{wallet_team_id}/reported-spend",
        headers=_auth_headers(token, {INTERNAL_ACTOR_HEADER: TASKS_COMPUTE_ACTOR}),
        json=body,
        timeout=REPORTED_SPEND_TIMEOUT_SECONDS,
        trust_env=False,
    )
    try:
        parsed: Any = response.json()
    except ValueError:
        parsed = None
    return ReportedSpendResponse(
        status_code=response.status_code,
        body=parsed if isinstance(parsed, dict) else None,
        text=response.text,
    )


@dataclasses.dataclass(frozen=True)
class UsageReportPage:
    rows: list[dict[str, Any]]
    truncated: bool
    next_cursor: str | None


def get_usage_report(params: dict[str, str]) -> UsageReportPage:
    url, token = _config()
    try:
        response = httpx.get(
            f"{url}/internal/usage/report",
            headers=_auth_headers(token, {INTERNAL_ACTOR_HEADER: TASKS_COMPUTE_ACTOR}),
            params=params,
            timeout=USAGE_REPORT_TIMEOUT_SECONDS,
            trust_env=False,
        )
    except httpx.HTTPError as exc:
        raise AIGatewayInternalError(f"usage report read failed: {exc}") from exc
    if response.status_code >= 400:
        raise AIGatewayInternalError(f"usage report read failed: {_error_detail(response)}")
    try:
        data: Any = response.json()
    except ValueError as exc:
        raise AIGatewayInternalError(f"usage report read failed: {exc}") from exc
    if not isinstance(data, dict):
        raise AIGatewayInternalError("usage report response was not an object")
    rows = data.get("rows")
    if not isinstance(rows, list):
        raise AIGatewayInternalError("usage report response had no rows")
    truncated = data.get("truncated")
    if not isinstance(truncated, bool):
        raise AIGatewayInternalError("usage report response had no truncated flag")
    cursor = data.get("next_cursor")
    if cursor is not None and not isinstance(cursor, str):
        raise AIGatewayInternalError("usage report response had an invalid cursor")
    return UsageReportPage(
        rows=[row for row in rows if isinstance(row, dict)],
        truncated=truncated,
        next_cursor=cursor,
    )


def get_usage_report_rows(params: dict[str, str]) -> list[dict[str, Any]]:
    page_params = {**params, "order_by": "key"}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    while True:
        page = get_usage_report(page_params)
        rows.extend(page.rows)
        if not page.truncated:
            return rows
        if not page.next_cursor:
            raise AIGatewayInternalError("usage report is truncated but returned no cursor")
        if page.next_cursor in seen:
            raise AIGatewayInternalError("usage report returned a repeated cursor")
        seen.add(page.next_cursor)
        page_params = {**params, "order_by": "key", "cursor": page.next_cursor}


@frozen
class BillingUsageRow:
    org_id: str
    product: str
    interval_start: datetime
    credit_paid_micros: int
    overage_micros: int
    free_micros: int


@frozen
class BillingUsagePage:
    rows: list[BillingUsageRow]
    final_through: datetime
    next_cursor: str | None


@frozen
class BillingUsage:
    rows: list[BillingUsageRow]
    # A bucket is final when it ends at or before this time.
    final_through: datetime


def get_billing_usage_page(params: dict[str, str | list[str]]) -> BillingUsagePage:
    url, token = _config()
    try:
        response = httpx.get(
            f"{url}/internal/billing/v1/usage",
            headers=_auth_headers(token),
            params=params,
            timeout=BILLING_USAGE_TIMEOUT_SECONDS,
            trust_env=False,
        )
    except httpx.HTTPError as exc:
        raise AIGatewayInternalError(f"billing usage read failed: {exc!r}") from exc
    if response.status_code == 404:
        raise AIGatewayRouteNotFound("billing usage read failed: HTTP 404")
    if response.status_code >= 400:
        raise AIGatewayInternalError(
            f"billing usage read failed: HTTP {response.status_code}: {_error_detail(response)}"
        )
    try:
        data: Any = response.json()
    except ValueError as exc:
        raise AIGatewayInternalError(f"billing usage read failed: {exc}") from exc
    if not isinstance(data, dict):
        raise AIGatewayInternalError("billing usage response was not an object")
    rows = data.get("usage")
    if not isinstance(rows, list):
        raise AIGatewayInternalError("billing usage response had no usage rows")
    cursor = data.get("next_cursor")
    if cursor is not None and (not isinstance(cursor, str) or not cursor):
        raise AIGatewayInternalError("billing usage response had an invalid cursor")
    return BillingUsagePage(
        rows=[_parse_billing_usage_row(row) for row in rows],
        final_through=_parse_time(data.get("final_through"), "final_through"),
        next_cursor=cursor,
    )


def get_billing_usage(
    *,
    interval: Literal["hour", "day"],
    start: datetime,
    end: datetime,
    org_ids: Sequence[str] = (),
    limit: int | None = None,
) -> BillingUsage:
    params: dict[str, str | list[str]] = {"interval": interval, "from": _format_time(start), "to": _format_time(end)}
    if org_ids:
        params["org_id"] = list(org_ids)
    if limit is not None:
        params["limit"] = str(limit)
    page = get_billing_usage_page(params)
    # The cursor holds the first page's final_through. A page with another value read a different
    # snapshot, so its rows can repeat or leave out rows from the pages before it.
    final_through = page.final_through
    rows: list[BillingUsageRow] = []
    seen: set[str] = set()
    while True:
        if page.final_through != final_through:
            raise AIGatewayInternalError("billing usage pages returned different final_through values")
        rows.extend(page.rows)
        if page.next_cursor is None:
            return BillingUsage(rows=rows, final_through=final_through)
        if page.next_cursor in seen:
            raise AIGatewayInternalError("billing usage returned a repeated cursor")
        seen.add(page.next_cursor)
        page = get_billing_usage_page({**params, "cursor": page.next_cursor})


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("billing usage times must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise AIGatewayInternalError(f"billing usage response had no {name}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AIGatewayInternalError(f"billing usage response had an invalid {name}") from exc
    if parsed.tzinfo is None:
        raise AIGatewayInternalError(f"billing usage response had an invalid {name}")
    return parsed


def _parse_micros(row: dict[str, Any], name: str) -> int:
    value = row.get(name)
    # bool is a subclass of int, so check for it first.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AIGatewayInternalError(f"billing usage row had an invalid {name}")
    return value


def _parse_billing_usage_row(row: Any) -> BillingUsageRow:
    # Fail the whole read on a bad row. Billing keeps the first amount it records for a day, so a
    # dropped row would under-bill that day for good.
    if not isinstance(row, dict):
        raise AIGatewayInternalError("billing usage row was not an object")
    org_id = row.get("org_id")
    product = row.get("product")
    if not isinstance(product, str) or not product:
        raise AIGatewayInternalError("billing usage row had an invalid product")
    if not isinstance(org_id, str):
        raise AIGatewayInternalError("billing usage row had an invalid org_id")
    try:
        canonical_org_id = str(uuid.UUID(org_id))
    except ValueError as exc:
        raise AIGatewayInternalError("billing usage row had an invalid org_id") from exc
    return BillingUsageRow(
        org_id=canonical_org_id,
        product=product,
        interval_start=_parse_time(row.get("interval_start"), "interval_start"),
        credit_paid_micros=_parse_micros(row, "credit_paid_micros"),
        overage_micros=_parse_micros(row, "overage_micros"),
        free_micros=_parse_micros(row, "free_micros"),
    )


def _error_detail(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(body, dict):
        return str(body.get("error") or body.get("message") or body)
    return f"HTTP {response.status_code}"
