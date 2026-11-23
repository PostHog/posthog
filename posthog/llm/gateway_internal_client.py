import json
import uuid
import dataclasses
from typing import Any, TypeGuard

from django.conf import settings

import httpx

from posthog.dataclasses import frozen

INTERNAL_API_TIMEOUT_SECONDS = 5.0
REPORTED_SPEND_TIMEOUT_SECONDS = 2.0
USAGE_REPORT_TIMEOUT_SECONDS = 35.0
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
INTERNAL_ACTOR_HEADER = "X-Internal-Actor"
# Ledger provenance tag (meta.source): admin-originated vs the billing path's
# "billing". The acting human is audited in ActivityLog, not here.
ADMIN_ACTOR = "posthog-admin"
TASKS_COMPUTE_ACTOR = "tasks-compute"
BILLING_ACTOR = "billing"
# A body that the route doesn't take, or an operation ID or reload key that the gateway holds with
# another amount. Every other failure, including 401, 403, 404 and 429, can pass once the gateway, its
# keys or its config recover.
REJECTED_STATUS_CODES = frozenset({400, 409})
SIGNED_ENVELOPE_FIELDS = ("body", "signed_at", "key_id", "signature")
SIGNED_MESSAGE_ROUTES = {
    "ai_funding_added": "/internal/accounts/{organization_id}/credits",
    "ai_funding_reversed": "/internal/accounts/{organization_id}/credits/reversal",
    "ai_withdrawal_requested": "/internal/accounts/{organization_id}/credits/withdrawal",
    "ai_reload_outcome": "/internal/accounts/{organization_id}/reload-outcome",
}


class AIGatewayInternalError(Exception):
    """An ai-gateway internal admin API call failed."""


class AIGatewayNotConfigured(AIGatewayInternalError):
    """AI_GATEWAY_INTERNAL_URL / AI_GATEWAY_INTERNAL_TOKEN are not set."""


class AIGatewayRequestRejected(AIGatewayInternalError):
    """The gateway refused the request itself (400 or 409), so sending it again fails the same way."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


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


class MalformedSignedMessage(ValueError):
    """A signed envelope that PostHog can't route, so sending it again fails the same way."""


@frozen
class SignedMessage:
    """A signed envelope as PostHog received it, with the two body fields that route it.

    PostHog holds no signing key, so it never checks the signature. The receiver checks it over the exact
    `body` string, so PostHog sends the envelope on unchanged.
    """

    envelope: dict[str, Any]
    type: str
    organization_id: str


def read_signed_message(envelope: object) -> SignedMessage:
    """Read the type and the organization ID from the body of a signed envelope.

    Raises `MalformedSignedMessage` when a field of the envelope isn't a string, or the body isn't a JSON
    object. It also raises it when the body has no type or no organization ID.
    """
    if not isinstance(envelope, dict) or not all(isinstance(envelope.get(f), str) for f in SIGNED_ENVELOPE_FIELDS):
        raise MalformedSignedMessage("the envelope needs body, signed_at, key_id and signature as strings")
    try:
        body: Any = json.loads(envelope["body"])
    except ValueError as exc:
        raise MalformedSignedMessage("the envelope's body isn't JSON") from exc
    if not isinstance(body, dict):
        raise MalformedSignedMessage("the envelope's body isn't a JSON object")
    message_type = body.get("type")
    if not isinstance(message_type, str) or not message_type:
        raise MalformedSignedMessage("the envelope's body has no type")
    organization_id = body.get("organization_id")
    if not _is_canonical_uuid(organization_id):
        raise MalformedSignedMessage("the envelope's body has no organization ID")
    return SignedMessage(envelope=envelope, type=message_type, organization_id=organization_id)


def post_signed_message(message: SignedMessage) -> object:
    """Post a message that billing signed for the gateway, unchanged, to the route for its body type.

    Returns the gateway's 200 answer, parsed from JSON. Raises `MalformedSignedMessage` for a body type that
    no route takes, and `AIGatewayRequestRejected` for a 400 or a 409. Every other answer, and no answer,
    raises `AIGatewayInternalError`.
    """
    route = SIGNED_MESSAGE_ROUTES.get(message.type)
    if route is None:
        raise MalformedSignedMessage(f"no gateway route takes {message.type}")
    url, token = _config()
    try:
        response = httpx.post(
            f"{url}{route.format(organization_id=message.organization_id)}",
            headers=_auth_headers(token, {INTERNAL_ACTOR_HEADER: BILLING_ACTOR}),
            json=message.envelope,
            timeout=INTERNAL_API_TIMEOUT_SECONDS,
            trust_env=False,
        )
    except httpx.HTTPError as exc:
        raise AIGatewayInternalError(f"{message.type} request failed: {exc}") from exc

    if response.status_code in REJECTED_STATUS_CODES:
        raise AIGatewayRequestRejected(_error_detail(response), response.status_code)
    if response.status_code != 200:
        raise AIGatewayInternalError(f"{message.type} answered {response.status_code}: {_error_detail(response)}")
    try:
        return response.json()
    except ValueError as exc:
        raise AIGatewayInternalError(f"{message.type} answer was not valid JSON: {exc}") from exc


def _is_canonical_uuid(value: object) -> TypeGuard[str]:
    # The ID goes into the route's path, so only the canonical form of a UUID passes.
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _error_detail(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(body, dict):
        return str(body.get("error") or body.get("message") or body)
    return f"HTTP {response.status_code}"
