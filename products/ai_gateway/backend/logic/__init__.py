"""Developer mode: short-lived AI gateway tokens for PostHog staff.

Django authenticates the employee, then mints a scoped `phe_` token on the gateway with
the employee's distinct_id pinned as the `user` node, so no request header can change
who a call is attributed to. Every token is recorded by hash, which is how the daily
cap is enforced and how tokens are listed and revoked.
"""

from __future__ import annotations

import hmac
import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

import requests
import structlog
import posthoganalytics

from posthog.api.email_verification import email_verification_pending
from posthog.models.scoping import team_scope
from posthog.models.user import User

from ..facade.contracts import DevToken, DevTokenRefused, DevTokenUsage, MintedDevToken
from ..facade.enums import DevTokenClient
from ..models import DevGatewayToken

logger = structlog.get_logger(__name__)

DEV_PRODUCT = "dev"
KILL_SWITCH_FLAG = "ai-gateway-dev-mode"
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
    """Why `user` cannot use developer mode, or None. Impersonation is request state and is
    checked by the caller before this."""
    if not user.is_active or not user.is_staff:
        return DevTokenRefused("not_staff", "Developer mode is only available to PostHog staff.", 403)
    if not (user.email or "").lower().endswith(STAFF_EMAIL_DOMAIN) or email_verification_pending(user):
        return DevTokenRefused("not_staff", "Developer mode needs a verified @posthog.com email.", 403)
    if not user.distinct_id:
        return DevTokenRefused("not_staff", "user has no distinct_id to attribute spend to.", 403)
    if not configured():
        return DevTokenRefused("unconfigured", "Developer mode is not configured on this instance.", 503)
    try:
        enabled = posthoganalytics.feature_enabled(
            KILL_SWITCH_FLAG, user.distinct_id, only_evaluate_locally=False, send_feature_flag_events=False
        )
    except Exception:
        # A flag-service outage must not take developer mode down; only an explicit False refuses.
        logger.warning("ai_gateway_dev_mode_flag_unavailable", exc_info=True)
        enabled = None
    if enabled is False:
        return DevTokenRefused("disabled", "Developer mode is turned off.", 403)
    return None


def _window_start() -> datetime:
    return timezone.now() - timedelta(days=1)


def _used_usd(user_id: int) -> Decimal:
    used = DevGatewayToken.objects.filter(user_id=user_id, created_at__gte=_window_start()).aggregate(
        total=Sum("cap_usd")
    )["total"]
    return used or Decimal("0")


def _to_dto(row: DevGatewayToken) -> DevToken:
    return DevToken(
        id=row.id,
        client=DevTokenClient(row.client),
        cap_usd=row.cap_usd,
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


def _reserve(user: User, client: DevTokenClient) -> DevGatewayToken:
    cap = token_cap_usd()
    with transaction.atomic():
        # Serializes one user's mints so two concurrent requests cannot both fit under the cap.
        User.objects.select_for_update().filter(pk=user.pk).first()
        used = _used_usd(user.pk)
        if used + cap > daily_cap_usd():
            raise DevTokenRefused(
                "daily_limit",
                f"daily developer mode limit is {daily_cap_usd()} USD; {used} USD of token caps minted in the last 24 hours",
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


def _call_mint(user: User, cap: Decimal) -> dict:
    body = {
        "cap_usd": str(cap),
        "ttl_seconds": settings.DEV_GATEWAY_TOKEN_TTL_SECONDS,
        "product": DEV_PRODUCT,
        "user": user.distinct_id,
    }
    try:
        response = _gateway_post("/v1/tokens", body)
    except requests.RequestException as e:
        raise DevTokenRefused("mint_failed", "AI gateway unreachable.", 503) from e
    if response.status_code != 201:
        logger.warning("ai_gateway_dev_mint_refused", status=response.status_code)
        raise DevTokenRefused("mint_failed", f"AI gateway refused the mint with HTTP {response.status_code}.", 503)
    try:
        minted = response.json()
    except ValueError as e:
        raise DevTokenRefused("mint_failed", "AI gateway mint response was not JSON.", 503) from e
    if not isinstance(minted, dict) or not minted.get("token") or not minted.get("expires_at"):
        raise DevTokenRefused("mint_failed", "AI gateway mint response had no token.", 503)
    return minted


def mint(user: User, client: DevTokenClient) -> MintedDevToken:
    with team_scope(settings.DEV_GATEWAY_TEAM_ID):
        row = _reserve(user, client)
        try:
            minted = _call_mint(user, row.cap_usd)
        except Exception:
            row.delete()
            raise
        token: str = minted["token"]
        row.token_hash = hashlib.sha256(token.encode()).hexdigest()
        row.expires_at = minted["expires_at"]
        row.save(update_fields=["token_hash", "expires_at"])
        row.refresh_from_db(fields=["expires_at"])
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


def usage(user: User) -> DevTokenUsage:
    with team_scope(settings.DEV_GATEWAY_TEAM_ID):
        active = DevGatewayToken.objects.filter(
            user_id=user.pk, token_hash__isnull=False, revoked_at__isnull=True, expires_at__gt=timezone.now()
        ).order_by("-created_at")
        tokens = [_to_dto(row) for row in active]
        used = _used_usd(user.pk)
    return DevTokenUsage(
        daily_cap_usd=daily_cap_usd(),
        used_usd=used,
        token_cap_usd=token_cap_usd(),
        ttl_seconds=settings.DEV_GATEWAY_TOKEN_TTL_SECONDS,
        tokens=tokens,
    )


def revoke(user: User, token_id: str | None) -> int:
    """Revokes one of `user`'s live tokens, or all of them when token_id is None. Returns how many
    the gateway deleted. A row is marked revoked only after the gateway confirms."""
    with team_scope(settings.DEV_GATEWAY_TEAM_ID):
        rows = DevGatewayToken.objects.filter(user_id=user.pk, token_hash__isnull=False, revoked_at__isnull=True)
        if token_id is not None:
            rows = rows.filter(id=token_id)
        targets = list(rows)
        if token_id is not None and not targets:
            raise DevTokenRefused("not_found", f"no live developer mode token with id {token_id}", 404)
        if not targets:
            return 0
        try:
            response = _gateway_post("/v1/tokens/revoke", {"token_hashes": [row.token_hash for row in targets]})
        except requests.RequestException as e:
            raise DevTokenRefused("revoke_failed", "AI gateway unreachable.", 503) from e
        if response.status_code != 200:
            raise DevTokenRefused(
                "revoke_failed", f"AI gateway refused the revoke with HTTP {response.status_code}.", 503
            )
        DevGatewayToken.objects.filter(id__in=[row.id for row in targets]).update(revoked_at=timezone.now())
    logger.info("ai_gateway_dev_tokens_revoked", user_id=user.pk, count=len(targets))
    try:
        return int(response.json().get("revoked_count", 0))
    except (ValueError, AttributeError, TypeError):
        return 0


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _code_key(code: str) -> str:
    return _CLI_CODE_CACHE_PREFIX + hashlib.sha256(code.encode()).hexdigest()


def authorize_cli(user: User, code_challenge: str) -> str:
    """Issues a one-time code the browser hands to the CLI's loopback listener. Only the
    holder of the PKCE verifier behind `code_challenge` can exchange it."""
    code = secrets.token_urlsafe(32)
    cache.set(_code_key(code), {"user_id": user.pk, "challenge": code_challenge}, CLI_CODE_TTL_SECONDS)
    return code


def exchange_cli_code(code: str, code_verifier: str) -> MintedDevToken:
    key = _code_key(code)
    grant = cache.get(key)
    # delete() reports whether this caller removed the key, so a replayed code loses the race.
    if not isinstance(grant, dict) or not cache.delete(key):
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
