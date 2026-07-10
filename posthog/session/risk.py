from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum
from math import asin, cos, radians, sin, sqrt
from typing import Optional

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY
from django.contrib.sessions.backends.base import SessionBase
from django.http import HttpRequest
from django.utils import timezone

import structlog
import posthoganalytics
from loginas.utils import is_impersonated_session

from posthog.geoip import get_geoip_location
from posthog.models import User
from posthog.session.models import Session
from posthog.utils import get_trusted_client_ip

logger = structlog.get_logger(__name__)


class RiskSignal(str, Enum):
    IMPOSSIBLE_TRAVEL = "impossible_travel"
    UA_CHANGE = "ua_change"
    NEW_COUNTRY = "new_country"


class RiskTier(IntEnum):
    NONE = 0
    MEDIUM = 1
    HIGH = 2


@dataclass
class Baseline:
    latitude: Optional[float]
    longitude: Optional[float]
    country_code: Optional[str]
    ua_signature: Optional[str]
    baseline_at: Optional[datetime]  # when this known-good snapshot was recorded


@dataclass
class Context:
    latitude: Optional[float]
    longitude: Optional[float]
    country_code: Optional[str]
    ua_signature: Optional[str]


def ua_signature(user_agent: Optional[str]) -> Optional[str]:
    if not user_agent:
        return None
    from user_agents import parse  # noqa: PLC0415 — heavy dep, request-time only (matches get_short_user_agent)

    ua = parse(user_agent)
    device = "mobile" if ua.is_mobile else "tablet" if ua.is_tablet else "pc" if ua.is_pc else "other"
    return f"{ua.browser.family}|{ua.os.family}|{device}".lower()


def current_request_context(request: HttpRequest) -> Context:
    """Geo + UA signature for the current request, used by evaluate_session_risk to score against
    the baseline and to advance it."""
    # Trusted-proxy-validated IP: a spoofed X-Forwarded-For must not drive a security decision.
    ip = get_trusted_client_ip(request)
    loc = get_geoip_location(ip) if ip else {}
    return Context(
        latitude=loc.get("latitude"),
        longitude=loc.get("longitude"),
        country_code=loc.get("country_code"),
        ua_signature=ua_signature(request.headers.get("user-agent")),
    )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(a))


def evaluate_signals(baseline: Baseline, ctx: Context, *, now: datetime) -> set[RiskSignal]:
    signals: set[RiskSignal] = set()

    if baseline.ua_signature and ctx.ua_signature and baseline.ua_signature != ctx.ua_signature:
        signals.add(RiskSignal.UA_CHANGE)

    if baseline.country_code and ctx.country_code and baseline.country_code != ctx.country_code:
        signals.add(RiskSignal.NEW_COUNTRY)

    if (
        baseline.latitude is not None
        and baseline.longitude is not None
        and baseline.baseline_at is not None
        and ctx.latitude is not None
        and ctx.longitude is not None
    ):
        distance = haversine_km(baseline.latitude, baseline.longitude, ctx.latitude, ctx.longitude)
        # Clamp elapsed to a floor rather than gating the check on it: a short gap with a huge
        # distance is the *most* impossible travel, so it must not be skipped. The floor only bounds
        # the implied velocity (and avoids div-by-zero / negative elapsed from clock skew).
        elapsed = max((now - baseline.baseline_at).total_seconds(), settings.RISK_ELAPSED_FLOOR_S)
        if (
            distance > settings.RISK_DISTANCE_FLOOR_KM
            and distance / (elapsed / 3600.0) > settings.RISK_VELOCITY_MAX_KMH
        ):
            signals.add(RiskSignal.IMPOSSIBLE_TRAVEL)

    return signals


def tier_for(signals: set[RiskSignal]) -> RiskTier:
    if RiskSignal.IMPOSSIBLE_TRAVEL in signals or len(signals) >= 2:
        return RiskTier.HIGH
    if signals:
        return RiskTier.MEDIUM
    return RiskTier.NONE


@dataclass
class RiskFlags:
    detection: bool
    step_up: bool
    session_end: bool


def _enabled(key: str, user: User) -> bool:
    # only_evaluate_locally keeps this off the network on the request hot path; an unloaded
    # flag returns None, which bool() collapses to False (fail-closed for enforcement).
    return bool(
        posthoganalytics.feature_enabled(
            key,
            str(user.distinct_id),
            person_properties={"email": user.email},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )


def risk_flags(user: User) -> RiskFlags:
    # session-risk-detection is the master gate: off ⇒ everything off.
    if not _enabled("session-risk-detection", user):
        return RiskFlags(detection=False, step_up=False, session_end=False)
    return RiskFlags(
        detection=True,
        step_up=_enabled("session-risk-step-up", user),
        session_end=_enabled("session-risk-session-end", user),
    )


def _baseline_for_session(session_key: str) -> Optional[Baseline]:
    row = (
        Session.objects.filter(session_key=session_key)
        .values("latitude", "longitude", "country_code", "ua_signature", "baseline_at")
        .first()
    )
    if row is None:
        return None
    return Baseline(**row)


def advance_baseline(session_key: str, baseline: Baseline, ctx: Context, *, now: datetime) -> None:
    """Record the current request as the new known-good baseline. Called only for low-risk (NONE)
    requests, so a suspicious request can never become the reference it would be scored against.

    Skips when the request has no usable geo fix (keeps the last good snapshot intact and its geo
    paired with its timestamp), and throttles refreshes to RISK_BASELINE_REFRESH_S to avoid a write
    on every request. A NULL baseline_at (fresh login, or detection just enabled) bypasses the
    throttle so the anchor is established immediately.
    """
    if ctx.latitude is None or ctx.longitude is None:
        return
    if (
        baseline.baseline_at is not None
        and (now - baseline.baseline_at).total_seconds() < settings.RISK_BASELINE_REFRESH_S
    ):
        return
    Session.objects.filter(session_key=session_key).update(
        latitude=ctx.latitude,
        longitude=ctx.longitude,
        country_code=ctx.country_code,
        ua_signature=ctx.ua_signature,
        baseline_at=now,
    )


def _risk_signature(tier: RiskTier, signals: set[RiskSignal]) -> str:
    """Identity of an anomaly for dedup purposes: its tier + the set of signals that produced it. An
    escalation (new/added signal, higher tier) is a new incident; the same signals flapping is not."""
    return f"{tier.name}:{','.join(sorted(signal.value for signal in signals))}"


def _should_emit_risk(session: SessionBase, tier: RiskTier, signals: set[RiskSignal], *, now: datetime) -> bool:
    """Dedup gate. A flagged session is re-scored on every request; without this it would emit
    telemetry and re-assert step-up every time, inflating counts and hammering the session store.

    Returns True (and records the signature + timestamp on the session) only when the anomaly's
    signature differs from the last emitted one or the re-emit cooldown has elapsed, so a persistent
    anomaly surfaces once per window instead of once per request. Never touches the baseline, so
    detection integrity is unaffected: the request is still scored the same next time.
    """
    signature = _risk_signature(tier, signals)
    last_signature = session.get(settings.SESSION_RISK_LAST_SIG_KEY)
    last_emit_at = session.get(settings.SESSION_RISK_LAST_EMIT_AT_KEY) or 0.0
    now_epoch = now.timestamp()
    if signature == last_signature and (now_epoch - last_emit_at) < settings.RISK_REEMIT_COOLDOWN_S:
        return False
    session[settings.SESSION_RISK_LAST_SIG_KEY] = signature
    session[settings.SESSION_RISK_LAST_EMIT_AT_KEY] = now_epoch
    return True


def evaluate_session_risk(request: HttpRequest) -> RiskTier:
    """Per-request risk orchestrator. Returns the *effective* tier the middleware should act on.

    Report-only by default: emits `session_risk_detected` telemetry for any non-NONE tier when
    detection is on, and only returns HIGH (to end the session) or sets `step_up_required` when the
    corresponding flag is on. The master `detection` flag gates everything — off ⇒ silent NONE.
    """
    user = request.user
    if not isinstance(user, User) or not user.is_authenticated:
        return RiskTier.NONE
    if BACKEND_SESSION_KEY not in request.session:
        return RiskTier.NONE
    session_key = request.session.session_key
    if not session_key:
        return RiskTier.NONE
    if is_impersonated_session(request):
        return RiskTier.NONE

    flags = risk_flags(user)
    if not flags.detection:
        return RiskTier.NONE

    baseline = _baseline_for_session(session_key)
    if baseline is None:
        return RiskTier.NONE

    ctx = current_request_context(request)
    now = timezone.now()
    signals = evaluate_signals(baseline, ctx, now=now)
    tier = tier_for(signals)
    if tier == RiskTier.NONE:
        # Low-risk request: roll the known-good baseline forward (or establish it when NULL). A
        # suspicious request never reaches here, so it can't poison the reference it's scored against.
        advance_baseline(session_key, baseline, ctx, now=now)
        return RiskTier.NONE

    effective = RiskTier.NONE
    enforced = False
    needs_step_up = False
    if tier == RiskTier.HIGH and flags.session_end:
        effective = RiskTier.HIGH
        enforced = True
    elif tier >= RiskTier.MEDIUM and flags.step_up:
        # Step-up is a side effect gated elsewhere; the middleware does not short-circuit on it. This
        # also catches a HIGH detection when session_end is off but step_up is on (graceful degradation).
        needs_step_up = True
        enforced = True

    # `effective` is computed above and returned regardless, so session-end is never suppressed.
    should_emit = _should_emit_risk(request.session, tier, signals, now=now)

    # Enforcement is independent of the telemetry dedup: apply step-up whenever it is needed and not
    # already set, even when the identical anomaly's telemetry is being deduped. Otherwise enabling
    # step-up mid-session would leave an already-flagged session unenforced until the cooldown expires.
    set_step_up = needs_step_up and not request.session.get(settings.SESSION_STEP_UP_REQUIRED_KEY)
    if set_step_up:
        request.session[settings.SESSION_STEP_UP_REQUIRED_KEY] = True

    # Persist the step-up flag and/or the dedup markers _should_emit_risk just wrote, now rather than
    # relying on SessionMiddleware, which skips save() on a 5xx response — otherwise a server error
    # here would drop the step-up requirement.
    if should_emit or set_step_up:
        request.session.save()

    if should_emit:
        # Telemetry must never break the request: a capture failure here would otherwise 500 an
        # otherwise-valid authenticated request from the request-phase middleware.
        try:
            posthoganalytics.capture(
                distinct_id=str(user.distinct_id),
                event="session_risk_detected",
                properties={
                    "signals": sorted(signal.value for signal in signals),
                    "tier": tier.name,
                    "enforced": enforced,
                },
            )
        except Exception:
            logger.exception("session_risk telemetry capture failed")

    return effective
