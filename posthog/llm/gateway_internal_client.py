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


class AIGatewayInternalError(Exception):
    """An ai-gateway internal admin API call failed."""


class AIGatewayNotConfigured(AIGatewayInternalError):
    """AI_GATEWAY_INTERNAL_URL / AI_GATEWAY_INTERNAL_TOKEN are not set."""


class AIGatewayBudgetSuperseded(AIGatewayInternalError):
    """A concurrent write published a newer budget for this node.

    The durable row still committed, so the write happened; the limit now being
    enforced is someone else's. Separate from a failure so a re-run can report
    "not mine" instead of retrying a write that cannot win.
    """


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
class Budget:
    team_id: int
    scope_type: str
    # The value the gateway stored. It sanitizes on write (control-strip, length
    # bound) exactly as admission sanitizes a request's node, so a caller that
    # sent an unsanitary value gets the stored form back here rather than the one
    # it asked for — and a budget keyed on the other string would never bind.
    scope_value: str
    limit_usd: str
    window_seconds: int


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


def _parse_budget(row: dict[str, Any], default_team_id: int) -> Budget:
    return Budget(
        team_id=int(row.get("team_id", default_team_id)),
        scope_type=row.get("scope_type", ""),
        scope_value=row.get("scope_value", ""),
        limit_usd=row.get("limit_usd", ""),
        window_seconds=int(row.get("window_seconds", 0)),
    )


def set_budget(team_id: int, scope_type: str, scope_value: str, limit_usd: str, window_seconds: int) -> Budget:
    """Upsert one attribution node's spend budget for a team.

    Budgets are per team: every key the enforcer builds is namespaced by team_id,
    so there is no fleet-wide pool to set here. A node with no row is unbudgeted,
    and enforcement fails open, so this is a ceiling rather than a hard floor —
    the team wallet remains the only thing that cannot be bypassed.

    Carries no idempotency key: the write is a config replace, so a re-run is
    inherently idempotent. Raises AIGatewayBudgetSuperseded when a concurrent
    write already published a newer limit for the same node.
    """
    url, token = _config()
    try:
        response = httpx.put(
            f"{url}/internal/teams/{team_id}/budgets",
            headers=_auth_headers(token, {INTERNAL_ACTOR_HEADER: ADMIN_ACTOR}),
            json={
                "scope_type": scope_type,
                "scope_value": scope_value,
                "limit_usd": limit_usd,
                "window_seconds": window_seconds,
            },
            timeout=INTERNAL_API_TIMEOUT_SECONDS,
            trust_env=False,
        )
    except httpx.HTTPError as exc:
        raise AIGatewayInternalError(f"budget write failed: {exc}") from exc

    if response.status_code == 409:
        raise AIGatewayBudgetSuperseded(_error_detail(response))
    if response.status_code >= 400:
        raise AIGatewayInternalError(_error_detail(response))

    try:
        data = response.json()
    except ValueError as exc:
        raise AIGatewayInternalError(f"budget response was not valid JSON: {exc}") from exc
    # A 2xx with a partial body would coerce to an empty scope_value, which reads
    # as a budget on a different node than the one requested.
    if not data.get("scope_value") or data.get("limit_usd") is None:
        raise AIGatewayInternalError("budget response missing required fields (scope_value/limit_usd)")
    return _parse_budget(data, team_id)


def list_budgets(team_id: int) -> list[Budget]:
    url, token = _config()
    try:
        response = httpx.get(
            f"{url}/internal/teams/{team_id}/budgets",
            headers=_auth_headers(token),
            timeout=INTERNAL_API_TIMEOUT_SECONDS,
            trust_env=False,
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AIGatewayInternalError(f"budget read failed: {exc}") from exc
    return [_parse_budget(row, team_id) for row in data.get("budgets") or []]


def _error_detail(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(body, dict):
        return str(body.get("error") or body.get("message") or body)
    return f"HTTP {response.status_code}"
