import dataclasses
from typing import TYPE_CHECKING, Any

from django.conf import settings

import httpx

if TYPE_CHECKING:
    from posthog.models.user import User

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
USER_SCOPE_TYPE = "user"


def user_spend_node(user: "User") -> str:
    """The node the gateway attributes this user's spend to; budgets must key the same node."""
    return user.distinct_id or f"user_{user.id}"


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


def _budgets_path(team_id: int) -> str:
    return f"/internal/teams/{team_id}/budgets"


def get_user_budget(team_id: int, scope_value: str) -> UserBudget | None:
    # The gateway serves no single-node read; one row per person keeps the scan small.
    response = _request("GET", _budgets_path(team_id), what="budget read")
    data = _json_body(response, "budget")
    for row in data.get("budgets") or []:
        if row.get("scope_type") == USER_SCOPE_TYPE and row.get("scope_value") == scope_value:
            return _user_budget(row)
    return None


def set_user_budget(team_id: int, scope_value: str, limit_usd: str, window_seconds: int) -> UserBudget:
    response = _request(
        "PUT",
        _budgets_path(team_id),
        what="budget write",
        extra_headers={INTERNAL_ACTOR_HEADER: USER_ACTOR},
        json={
            "scope_type": USER_SCOPE_TYPE,
            "scope_value": scope_value,
            "limit_usd": limit_usd,
            "window_seconds": window_seconds,
        },
    )
    return _user_budget(_json_body(response, "budget"))


def clear_user_budget(team_id: int, scope_value: str) -> None:
    response = _request(
        "DELETE",
        _budgets_path(team_id),
        what="budget delete",
        extra_headers={INTERNAL_ACTOR_HEADER: USER_ACTOR},
        params={"scope_type": USER_SCOPE_TYPE, "scope_value": scope_value},
        tolerated_statuses=frozenset({404}),
    )
    # The gateway's not_found envelope means the row was already gone (cleared); a bare router 404 means no budgets route.
    if response.status_code == 404 and _error_code(response) != "not_found":
        raise AIGatewayInternalError(_error_detail(response), status_code=404)


def _error_code(response: httpx.Response) -> str | None:
    try:
        body: Any = response.json()
    except ValueError:
        return None
    return body.get("code") if isinstance(body, dict) else None
