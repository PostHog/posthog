import dataclasses
from typing import Any

from django.conf import settings

import httpx

INTERNAL_API_TIMEOUT_SECONDS = 5.0
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
INTERNAL_ACTOR_HEADER = "X-Internal-Actor"
# Ledger provenance tag (meta.source): admin-originated vs the billing path's
# "billing". The acting human is audited in ActivityLog, not here.
ADMIN_ACTOR = "posthog-admin"
BILLING_ACTOR = "billing"
# A bad body, or an Idempotency-Key the gateway holds with another amount. Every other
# failure, including 401, 403, 404 and 429, can pass once the gateway or its config recovers.
REJECTED_STATUS_CODES = frozenset({400, 409})


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
class OrgLedgerResult:
    org_id: str
    entry_id: str
    amount_usd: str
    balance_usd: str
    duplicate: bool


@dataclasses.dataclass(frozen=True)
class CreditResult:
    team_id: int
    entry_id: str
    amount_usd: str
    balance_usd: str
    duplicate: bool


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


def add_credit(team_id: int, amount_usd: str, reason: str, idempotency_key: str) -> CreditResult:
    # Team-keyed top-up: funds the team wallet that admission draws down and
    # get_wallet() reads, so the credit is spendable today. The gateway's
    # org-scoped /internal/accounts/{org_id}/credits is the billing path but is
    # not yet drawn down at admission.
    # TODO(billing-entrypoint): revisit once credits are org-keyed end to end.
    url, token = _config()
    try:
        response = httpx.post(
            f"{url}/internal/teams/{team_id}/credits",
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


def grant_org_credit(org_id: str, amount_usd: str, reason: str, idempotency_key: str) -> OrgLedgerResult:
    """Add funding that billing collected to the organization's AI wallet, once per idempotency key."""
    return _post_org_ledger_entry(f"/internal/accounts/{org_id}/credits", org_id, amount_usd, reason, idempotency_key)


def reverse_org_credit(org_id: str, amount_usd: str, reason: str, idempotency_key: str) -> OrgLedgerResult:
    """Take back funding that billing refunded or lost to a dispute, once per idempotency key."""
    return _post_org_ledger_entry(
        f"/internal/accounts/{org_id}/credits/reversal", org_id, amount_usd, reason, idempotency_key
    )


def _post_org_ledger_entry(
    path: str, org_id: str, amount_usd: str, reason: str, idempotency_key: str
) -> OrgLedgerResult:
    url, token = _config()
    try:
        response = httpx.post(
            f"{url}{path}",
            headers=_auth_headers(
                token, {IDEMPOTENCY_KEY_HEADER: idempotency_key, INTERNAL_ACTOR_HEADER: BILLING_ACTOR}
            ),
            json={"amount_usd": amount_usd, "reason": reason},
            timeout=INTERNAL_API_TIMEOUT_SECONDS,
            trust_env=False,
        )
    except httpx.HTTPError as exc:
        raise AIGatewayInternalError(f"org ledger request failed: {exc}") from exc

    if response.status_code in REJECTED_STATUS_CODES:
        raise AIGatewayRequestRejected(_error_detail(response), response.status_code)
    if response.status_code >= 400:
        raise AIGatewayInternalError(_error_detail(response))

    try:
        data = response.json()
    except ValueError as exc:
        raise AIGatewayInternalError(f"org ledger response was not valid JSON: {exc}") from exc
    if not data.get("entry_id") or data.get("balance_usd") is None:
        raise AIGatewayInternalError("org ledger response missing required fields (entry_id/balance_usd)")
    return OrgLedgerResult(
        org_id=str(data.get("org_id", org_id)),
        entry_id=data["entry_id"],
        amount_usd=data.get("amount_usd", ""),
        balance_usd=data["balance_usd"],
        duplicate=bool(data.get("duplicate", False)),
    )


def _error_detail(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(body, dict):
        return str(body.get("error") or body.get("message") or body)
    return f"HTTP {response.status_code}"
