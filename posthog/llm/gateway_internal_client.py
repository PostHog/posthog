import dataclasses
from typing import Any

from django.conf import settings

import httpx

INTERNAL_API_TIMEOUT_SECONDS = 5.0
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"


class AIGatewayInternalError(Exception):
    """An ai-gateway internal admin API call failed."""


class AIGatewayNotConfigured(AIGatewayInternalError):
    """AI_GATEWAY_INTERNAL_URL / AI_GATEWAY_INTERNAL_TOKEN are not set."""


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
            headers=_auth_headers(token, {IDEMPOTENCY_KEY_HEADER: idempotency_key}),
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


def _error_detail(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(body, dict):
        return str(body.get("error") or body.get("message") or body)
    return f"HTTP {response.status_code}"
