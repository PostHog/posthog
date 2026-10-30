"""Short-lived AI gateway tokens for PostHog staff.

The gateway pins the staff user's distinct_id on each token, so no request header can
change who a call is attributed to.
"""

from __future__ import annotations

import hmac
import json
import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

import requests
import structlog
from urllib3.exceptions import NewConnectionError

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityLog, Change, Detail, log_activity
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.models.user import User
from posthog.redis import get_client

from .facade.contracts import (
    DevTeamUsage,
    DevToken,
    DevTokenActivity,
    DevTokenRefused,
    DevTokenUsage,
    DevUserUsage,
    MintedDevToken,
)
from .facade.enums import DevTokenClient, DevTokenStatus
from .models import DevGatewayToken

logger = structlog.get_logger(__name__)

DEV_PRODUCT = "dev"
STAFF_EMAIL_DOMAIN = "@posthog.com"
GATEWAY_TIMEOUT_SECONDS = 5
CLI_CODE_TTL_SECONDS = 120
_CLI_CODE_CACHE_PREFIX = "ai_gateway_dev_cli_code:"


def configured() -> bool:
    return bool(settings.DEV_GATEWAY_URL and settings.DEV_GATEWAY_MINT_KEY and settings.DEV_GATEWAY_TEAM_ID)


def gateway_base_url() -> str:
    return (settings.DEV_GATEWAY_URL or "").rstrip("/").removesuffix("/v1")


def token_cap_usd() -> Decimal:
    return Decimal(settings.DEV_GATEWAY_TOKEN_CAP_USD)


def daily_cap_usd() -> Decimal:
    return Decimal(settings.DEV_GATEWAY_DAILY_CAP_USD)


def eligibility_refusal(user: User) -> DevTokenRefused | None:
    """Impersonation is request state, so the caller checks it before this."""
    if not user.is_active or not user.is_staff:
        return DevTokenRefused("not_staff", "Developer mode is only available to PostHog staff.", 403)
    # None is a legacy account that predates verification.
    if not (user.email or "").lower().endswith(STAFF_EMAIL_DOMAIN) or user.is_email_verified is False:
        return DevTokenRefused("not_staff", "Developer mode needs a verified @posthog.com email.", 403)
    if not user.distinct_id:
        return DevTokenRefused(
            "not_staff", "Your account has no distinct_id, so spend can't be attributed to you.", 403
        )
    if not configured():
        return DevTokenRefused("unconfigured", "Developer mode is not configured on this instance.", 503)
    return None


def _window_start() -> datetime:
    return timezone.now() - timedelta(days=1)


def _used_usd(user_id: int) -> Decimal:
    used = DevGatewayToken.objects.filter(user_id=user_id, created_at__gte=_window_start()).aggregate(
        total=Sum("cap_usd")
    )["total"]
    return used or Decimal("0")


def _to_dto(row: DevGatewayToken, remaining: dict[str, Decimal] | None = None) -> DevToken:
    return DevToken(
        id=row.id,
        client=DevTokenClient(row.client),
        cap_usd=row.cap_usd,
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        status=(
            DevTokenStatus.REVOKED
            if row.revoked_at
            else DevTokenStatus.EXPIRED
            if row.expires_at and row.expires_at <= timezone.now()
            else DevTokenStatus.LIVE
        ),
        remaining_usd=(remaining or {}).get(row.token_hash or ""),
    )


def _reserve(user: User, client: DevTokenClient) -> DevGatewayToken:
    cap = token_cap_usd()
    with transaction.atomic():
        # Serializes one user's mints so two concurrent requests cannot both fit under the cap.
        User.objects.select_for_update().filter(pk=user.pk).first()
        used = _used_usd(user.pk)
        if used + cap > daily_cap_usd():
            oldest = (
                DevGatewayToken.objects.filter(user_id=user.pk, created_at__gte=_window_start())
                .order_by("created_at")
                .values_list("created_at", flat=True)
                .first()
            )
            available_at = (oldest + timedelta(days=1)) if oldest else timezone.now()
            raise DevTokenRefused(
                "daily_limit",
                f"You've used ${used:.2f} of your ${daily_cap_usd():.2f} limit for the last 24 hours. "
                f"You can create another token at {available_at:%Y-%m-%d %H:%M} UTC.",
                429,
            )
        return DevGatewayToken.objects.create(
            team_id=settings.DEV_GATEWAY_TEAM_ID, user=user, client=client.value, cap_usd=cap
        )


def _gateway_post(path: str, body: dict) -> requests.Response:
    return requests.post(
        f"{gateway_base_url()}{path}",
        json=body,
        headers={"Authorization": f"Bearer {settings.DEV_GATEWAY_MINT_KEY}"},
        timeout=GATEWAY_TIMEOUT_SECONDS,
        allow_redirects=False,
    )


class _UnreadableMint(DevTokenRefused):
    """The gateway answered 201, so it may have minted a token PostHog can't read."""


def _call_mint(user: User, cap: Decimal) -> dict:
    body = {
        "cap_usd": str(cap),
        "ttl_seconds": settings.DEV_GATEWAY_TOKEN_TTL_SECONDS,
        "product": DEV_PRODUCT,
        "user": user.distinct_id,
    }
    response = _gateway_post("/v1/tokens", body)
    if response.status_code != 201:
        logger.warning("ai_gateway_dev_mint_refused", status=response.status_code)
        raise DevTokenRefused(
            "mint_failed",
            f"The AI gateway rejected the request (HTTP {response.status_code}). Try again in a minute.",
            503,
        )
    try:
        minted = response.json()
    except ValueError as e:
        raise _UnreadableMint("mint_failed", "The AI gateway sent a response PostHog couldn't read.", 503) from e
    if not isinstance(minted, dict) or not minted.get("token") or not minted.get("expires_at"):
        raise _UnreadableMint("mint_failed", "The AI gateway sent a response without a token.", 503)
    return minted


def _log(user: User, row: DevGatewayToken, activity: str, changes: list[Change]) -> None:
    log_activity(
        organization_id=Team.objects.only("organization_id").get(pk=row.team_id).organization_id,
        team_id=row.team_id,
        user=user,
        was_impersonated=False,
        item_id=row.id,
        scope="DevGatewayToken",
        activity=activity,
        detail=Detail(name=f"Developer mode token for {user.email}", changes=changes),
    )


def _never_sent(error: requests.RequestException) -> bool:
    if isinstance(error, requests.ConnectTimeout):
        return True
    if not isinstance(error, (requests.Timeout, requests.ConnectionError)):
        return True
    # Refused connections and DNS failures arrive as a MaxRetryError whose reason is a NewConnectionError.
    return isinstance(getattr(error.args[0] if error.args else None, "reason", None), NewConnectionError)


def mint(user: User, client: DevTokenClient) -> MintedDevToken:
    with team_scope(settings.DEV_GATEWAY_TEAM_ID):
        row = _reserve(user, client)
        try:
            minted = _call_mint(user, row.cap_usd)
        except requests.RequestException as e:
            logger.warning("ai_gateway_dev_mint_unreachable", token_id=str(row.id), exc_info=True)
            # A read timeout or dropped response may follow a successful mint, so that reservation keeps counting.
            if _never_sent(e):
                row.delete()
            raise DevTokenRefused("mint_failed", "Couldn't reach the AI gateway. Try again in a minute.", 503) from e
        except _UnreadableMint:
            logger.warning("ai_gateway_dev_mint_unreadable", token_id=str(row.id))
            raise
        except Exception:
            row.delete()
            raise
        token: str = minted["token"]
        row.token_hash = hashlib.sha256(token.encode()).hexdigest()
        row.expires_at = minted["expires_at"]
        row.save(update_fields=["token_hash", "expires_at"])
        row.refresh_from_db(fields=["expires_at"])
        _log(
            user,
            row,
            "minted",
            [
                Change(type="DevGatewayToken", action="created", field="client", after=row.client),
                Change(type="DevGatewayToken", action="created", field="cap_usd", after=str(row.cap_usd)),
                Change(type="DevGatewayToken", action="created", field="expires_at", after=row.expires_at.isoformat()),
            ],
        )
    logger.info("ai_gateway_dev_token_minted", user_id=user.pk, token_id=str(row.id), client=client.value)
    assert row.expires_at is not None
    return MintedDevToken(
        id=row.id,
        token=token,
        cap_usd=row.cap_usd,
        expires_at=row.expires_at,
        gateway_url=gateway_base_url(),
        product=DEV_PRODUCT,
    )


def _remaining_by_hash(hashes: list[str]) -> dict[str, Decimal]:
    """Best effort: the settings table still renders without remaining amounts."""
    if not hashes:
        return {}
    try:
        response = _gateway_post("/v1/tokens/status", {"token_hashes": hashes})
    except requests.RequestException:
        logger.warning("ai_gateway_dev_status_unreachable", exc_info=True)
        return {}
    if response.status_code != 200:
        logger.warning("ai_gateway_dev_status_refused", status=response.status_code)
        return {}
    try:
        return {item["token_hash"]: Decimal(item["remaining_usd"]) for item in response.json()["tokens"]}
    except (ValueError, KeyError, TypeError, ArithmeticError):
        logger.warning("ai_gateway_dev_status_unreadable")
        return {}


def usage(user: User) -> DevTokenUsage:
    with team_scope(settings.DEV_GATEWAY_TEAM_ID):
        # Every token that counts against the daily limit, including revoked and expired ones.
        recent = DevGatewayToken.objects.filter(
            user_id=user.pk, token_hash__isnull=False, created_at__gte=_window_start()
        ).order_by("-created_at")
        live_hashes = [
            row.token_hash
            for row in recent
            if row.token_hash and not row.revoked_at and row.expires_at and row.expires_at > timezone.now()
        ]
        remaining = _remaining_by_hash(live_hashes)
        tokens = [_to_dto(row, remaining) for row in recent]
        used = _used_usd(user.pk)
    return DevTokenUsage(
        daily_cap_usd=daily_cap_usd(),
        used_usd=used,
        token_cap_usd=token_cap_usd(),
        ttl_seconds=settings.DEV_GATEWAY_TOKEN_TTL_SECONDS,
        tokens=tokens,
    )


def token_status(token: str) -> DevToken:
    """Holding the bearer is the credential, so this reveals only what its holder can already spend."""
    if not configured():
        raise DevTokenRefused("unconfigured", "Developer mode is not configured on this instance.", 503)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with team_scope(settings.DEV_GATEWAY_TEAM_ID):
        row = DevGatewayToken.objects.filter(token_hash=token_hash).first()
    if row is None:
        raise DevTokenRefused("not_found", "token is not a developer mode token", 404)
    live = not row.revoked_at and row.expires_at is not None and row.expires_at > timezone.now()
    return _to_dto(row, _remaining_by_hash([token_hash]) if live else None)


TEAM_USAGE_DAYS = 30
TEAM_ACTIVITY_LIMIT = 1000

# `$ai_product_source = 'pinned'` keeps out calls that only set an X-PostHog-Product header.
_SPEND_QUERY = """
SELECT
    properties.$ai_user AS ai_user,
    sumIf(toFloat(properties.$ai_total_cost_usd), timestamp > now() - INTERVAL 1 DAY),
    sumIf(toFloat(properties.$ai_total_cost_usd), timestamp > now() - INTERVAL 7 DAY),
    sum(toFloat(properties.$ai_total_cost_usd))
FROM events
WHERE event = '$ai_generation'
    AND timestamp > now() - INTERVAL 30 DAY
    AND properties.$ai_product = {product}
    AND properties.$ai_product_source = 'pinned'
GROUP BY ai_user
LIMIT 1000
"""


def team_usage_refusal(user: User) -> DevTokenRefused | None:
    refusal = eligibility_refusal(user)
    if refusal is not None:
        return refusal
    team = Team.objects.only("organization_id").get(pk=settings.DEV_GATEWAY_TEAM_ID)
    if not OrganizationMembership.objects.filter(user=user, organization_id=team.organization_id).exists():
        return DevTokenRefused("not_member", "Team usage is only shown to members of the paying project.", 403)
    return None


@frozen
class _Spend:
    day: Decimal = Decimal("0")
    week: Decimal = Decimal("0")
    month: Decimal = Decimal("0")


def _spend_by_distinct_id(team: Team) -> dict[str, _Spend]:
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.AI_GATEWAY_DEV_USAGE):
        response = execute_hogql_query(
            _SPEND_QUERY,
            placeholders={"product": ast.Constant(value=DEV_PRODUCT)},
            team=team,
            query_type="ai_gateway_dev_team_spend",
        )
    return {
        str(distinct_id): _Spend(
            day=Decimal(str(day or 0)), week=Decimal(str(week or 0)), month=Decimal(str(month or 0))
        )
        for distinct_id, day, week, month in response.results or []
        if distinct_id
    }


def _activity(team_id: int, since: datetime, rows: list[DevGatewayToken]) -> list[DevTokenActivity]:
    """A revoke entry records no owner, client or cap, so those come from the token row."""
    by_id = {str(row.id): row for row in rows}
    entries = (
        ActivityLog.objects.filter(team_id=team_id, scope="DevGatewayToken", created_at__gte=since)
        .select_related("user")
        .order_by("-created_at")[:TEAM_ACTIVITY_LIMIT]
    )
    result: list[DevTokenActivity] = []
    for entry in entries:
        row = by_id.get(entry.item_id or "")
        result.append(
            DevTokenActivity(
                at=entry.created_at,
                activity=entry.activity,
                actor_email=entry.user.email if entry.user else None,
                owner_email=row.user.email if row else None,
                client=DevTokenClient(row.client) if row else None,
                cap_usd=row.cap_usd if row else None,
            )
        )
    return result


def team_usage(viewer: User) -> DevTeamUsage:
    refusal = team_usage_refusal(viewer)
    if refusal is not None:
        raise refusal
    now = timezone.now()
    day_ago = now - timedelta(days=1)
    team = Team.objects.get(pk=settings.DEV_GATEWAY_TEAM_ID)
    with team_scope(team.pk):
        since = now - timedelta(days=TEAM_USAGE_DAYS)
        rows = list(
            DevGatewayToken.objects.filter(token_hash__isnull=False, created_at__gte=since).select_related("user")
        )
    spend = _spend_by_distinct_id(team)
    users = {row.user_id: row.user for row in rows}
    known_distinct_ids = {user.distinct_id for user in users.values() if user.distinct_id}
    for user in User.objects.filter(distinct_id__in=set(spend) - known_distinct_ids):
        users[user.pk] = user
    result: list[DevUserUsage] = []
    for user in users.values():
        mine = [row for row in rows if row.user_id == user.pk]
        spent = spend.pop(user.distinct_id or "", _Spend())
        result.append(
            DevUserUsage(
                user_id=user.pk,
                email=user.email,
                distinct_id=user.distinct_id or "",
                tokens_minted_24h=sum(1 for row in mine if row.created_at >= day_ago),
                tokens_minted_30d=len(mine),
                live_tokens=sum(1 for row in mine if not row.revoked_at and row.expires_at and row.expires_at > now),
                revoked_30d=sum(1 for row in mine if row.revoked_at),
                reserved_usd_24h=sum((row.cap_usd for row in mine if row.created_at >= day_ago), Decimal("0")),
                spend_usd_24h=spent.day,
                spend_usd_7d=spent.week,
                spend_usd_30d=spent.month,
                last_minted_at=max((row.created_at for row in mine), default=None),
            )
        )
    # Spend whose $ai_user matches no PostHog user still shows, so totals reconcile.
    for distinct_id, spent in spend.items():
        result.append(
            DevUserUsage(
                user_id=None,
                email=None,
                distinct_id=distinct_id,
                tokens_minted_24h=0,
                tokens_minted_30d=0,
                live_tokens=0,
                revoked_30d=0,
                reserved_usd_24h=Decimal("0"),
                spend_usd_24h=spent.day,
                spend_usd_7d=spent.week,
                spend_usd_30d=spent.month,
                last_minted_at=None,
            )
        )
    result.sort(key=lambda u: (u.spend_usd_30d, u.tokens_minted_30d), reverse=True)
    return DevTeamUsage(paying_team_id=team.pk, users=result, activity=_activity(team.pk, since, rows))


def revoke(user: User, token_id: str | None) -> int:
    """Returns the gateway's revoked count. Rows are marked revoked only after the gateway confirms."""
    with team_scope(settings.DEV_GATEWAY_TEAM_ID):
        rows = DevGatewayToken.objects.filter(
            user_id=user.pk, token_hash__isnull=False, revoked_at__isnull=True, expires_at__gt=timezone.now()
        )
        if token_id is not None:
            rows = rows.filter(id=token_id)
        targets = list(rows)
        if token_id is not None and not targets:
            raise DevTokenRefused("not_found", f"Token {token_id} is already revoked or expired.", 404)
        if not targets:
            return 0
        try:
            response = _gateway_post("/v1/tokens/revoke", {"token_hashes": [row.token_hash for row in targets]})
        except requests.RequestException as e:
            logger.warning("ai_gateway_dev_revoke_unreachable", user_id=user.pk, exc_info=True)
            raise DevTokenRefused("revoke_failed", "Couldn't reach the AI gateway. Try again in a minute.", 503) from e
        if response.status_code != 200:
            logger.warning("ai_gateway_dev_revoke_refused", user_id=user.pk, status=response.status_code)
            raise DevTokenRefused(
                "revoke_failed",
                f"The AI gateway rejected the revoke (HTTP {response.status_code}). Try again in a minute.",
                503,
            )
        try:
            revoked_count = int(response.json().get("revoked_count", 0))
        except (ValueError, AttributeError, TypeError):
            revoked_count = 0
        # The gateway fails the whole request if any hash fails, so a short count means some tokens
        # were already gone (expired or revoked elsewhere) and every target is dead either way.
        if revoked_count != len(targets):
            logger.warning(
                "ai_gateway_dev_revoke_count_mismatch", user_id=user.pk, sent=len(targets), revoked=revoked_count
            )
        revoked_at = timezone.now()
        DevGatewayToken.objects.filter(
            user_id=user.pk, team_id=settings.DEV_GATEWAY_TEAM_ID, id__in=[row.id for row in targets]
        ).update(revoked_at=revoked_at)
        # The bulk update skips save(), so each revoke is logged by hand.
        for row in targets:
            _log(
                user,
                row,
                "revoked",
                [Change(type="DevGatewayToken", action="changed", field="revoked_at", after=revoked_at.isoformat())],
            )
    logger.info("ai_gateway_dev_tokens_revoked", user_id=user.pk, count=len(targets))
    return revoked_count


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _code_key(code: str) -> str:
    return _CLI_CODE_CACHE_PREFIX + hashlib.sha256(code.encode()).hexdigest()


def authorize_cli(user: User, code_challenge: str) -> str:
    """Issues a one-time code the browser hands to the CLI's loopback listener. Only the
    holder of the PKCE verifier behind `code_challenge` can exchange it."""
    code = secrets.token_urlsafe(32)
    # The plain client talks to the primary, so the exchange can't miss a grant on a lagging replica.
    get_client().set(
        _code_key(code), json.dumps({"user_id": user.pk, "challenge": code_challenge}), ex=CLI_CODE_TTL_SECONDS
    )
    return code


def exchange_cli_code(code: str, code_verifier: str) -> MintedDevToken:
    # GET and DEL in one MULTI, so a replayed code reads nothing. GETDEL would need Redis 6.2.
    pipe = get_client().pipeline(transaction=True)
    pipe.get(_code_key(code))
    pipe.delete(_code_key(code))
    raw, _ = pipe.execute()
    grant = json.loads(raw) if raw else None
    if not isinstance(grant, dict):
        raise DevTokenRefused("invalid_code", "code is unknown, expired or already used", 400)
    if not hmac.compare_digest(_s256(code_verifier), grant["challenge"]):
        raise DevTokenRefused("invalid_code", "code_verifier does not match the code_challenge", 400)
    user = User.objects.filter(pk=grant["user_id"]).first()
    if user is None:
        raise DevTokenRefused("invalid_code", "code is unknown, expired or already used", 400)
    refusal = eligibility_refusal(user)
    if refusal is not None:
        raise refusal
    return mint(user, DevTokenClient.CLI)
