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

    def __init__(self, *args: object, status_code: int | None = None) -> None:
        super().__init__(*args)
        # Lets a caller tell a route the gateway does not serve from a gateway that
        # broke. None when the call never reached a response.
        self.status_code = status_code


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


def _request(
    method: str,
    path: str,
    *,
    what: str,
    extra_headers: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
    tolerated_statuses: frozenset[int] = frozenset(),
) -> httpx.Response:
    url, token = _config()
    try:
        # trust_env=False keeps the in-cluster call off the egress proxy.
        response = httpx.request(
            method,
            f"{url}{path}",
            headers=_auth_headers(token, extra_headers),
            json=json,
            params=params,
            timeout=INTERNAL_API_TIMEOUT_SECONDS,
            trust_env=False,
        )
    except httpx.HTTPError as exc:
        raise AIGatewayInternalError(f"{what} failed: {exc}") from exc
    if not response.is_success and response.status_code not in tolerated_statuses:
        raise AIGatewayInternalError(_error_detail(response), status_code=response.status_code)
    return response


def _json_body(response: httpx.Response, resource: str) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise AIGatewayInternalError(f"{resource} response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AIGatewayInternalError(f"{resource} response was not a JSON object")
    return data


def get_wallet(team_id: int) -> Wallet:
    response = _request("GET", f"/internal/admin/api/teams/{team_id}", what="wallet read")
    data = _json_body(response, "wallet")

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
    response = _request(
        "POST",
        f"/internal/teams/{team_id}/credits",
        what="credit request",
        extra_headers={IDEMPOTENCY_KEY_HEADER: idempotency_key, INTERNAL_ACTOR_HEADER: ADMIN_ACTOR},
        json={"amount_usd": amount_usd, "reason": reason},
    )
    data = _json_body(response, "credit")
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


# Must match the X-PostHog-User node used for gateway spend attribution.
USER_ACTOR = "posthog-user"


@dataclasses.dataclass(frozen=True)
class UserBudget:
    limit_usd: str
    window_seconds: int


def _user_budget(row: dict[str, Any]) -> UserBudget:
    try:
        window_seconds = int(row.get("window_seconds") or 0)
    except (TypeError, ValueError) as exc:
        raise AIGatewayInternalError(f"budget response had a non-numeric window: {exc}") from exc
    limit_usd = row.get("limit_usd")
    if not limit_usd or window_seconds <= 0:
        raise AIGatewayInternalError("budget response missing required fields (limit_usd/window_seconds)")
    return UserBudget(limit_usd=str(limit_usd), window_seconds=window_seconds)


# One budget lives at one per-user path, so a read never scans a team's whole
# collection. The gateway contract this client assumes:
#   - a 404 on any budget path means this gateway serves no budgets route at
#     all, never "this user has none";
#   - "this user has none" is a 2xx with no budget row ("budget": null);
#   - deleting a budget that does not exist still succeeds (idempotent delete).
# Splitting "no route" and "no budget" across status codes lets every verb agree
# on `available` for a gateway that holds no limits.


def _user_budget_path(team_id: int, scope_value: str) -> str:
    return f"/internal/teams/{team_id}/budgets/users/{scope_value}"


def get_user_budget(team_id: int, scope_value: str) -> UserBudget | None:
    response = _request("GET", _user_budget_path(team_id, scope_value), what="budget read")
    data = _json_body(response, "budget")
    row = data.get("budget")
    return _user_budget(row) if row else None


def set_user_budget(team_id: int, scope_value: str, limit_usd: str, window_seconds: int) -> UserBudget:
    # Replacing a budget does not move ledger funds, so it needs no idempotency key.
    response = _request(
        "PUT",
        _user_budget_path(team_id, scope_value),
        what="budget write",
        extra_headers={INTERNAL_ACTOR_HEADER: USER_ACTOR},
        json={"limit_usd": limit_usd, "window_seconds": window_seconds},
    )
    data = _json_body(response, "budget")
    row = data.get("budget")
    if not row:
        raise AIGatewayInternalError("budget response missing required fields (limit_usd/window_seconds)")
    return _user_budget(row)


def clear_user_budget(team_id: int, scope_value: str) -> None:
    """Remove one person's budget. A 404 means the gateway serves no budgets route,
    not that the user had none. Deleting a missing budget still succeeds."""
    _request(
        "DELETE",
        _user_budget_path(team_id, scope_value),
        what="budget delete",
        extra_headers={INTERNAL_ACTOR_HEADER: USER_ACTOR},
    )
