from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum
from math import asin, cos, radians, sin, sqrt
from typing import Optional

import posthoganalytics

from posthog.models import User

RISK_DISTANCE_FLOOR_KM = 500.0
RISK_ELAPSED_FLOOR_S = 300.0
RISK_VELOCITY_MAX_KMH = 1000.0


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
    last_activity: Optional[datetime]


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
        and baseline.last_activity is not None
        and ctx.latitude is not None
        and ctx.longitude is not None
    ):
        distance = haversine_km(baseline.latitude, baseline.longitude, ctx.latitude, ctx.longitude)
        elapsed = (now - baseline.last_activity).total_seconds()
        if distance > RISK_DISTANCE_FLOOR_KM and elapsed > RISK_ELAPSED_FLOOR_S:
            if distance / (elapsed / 3600.0) > RISK_VELOCITY_MAX_KMH:
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
            key, str(user.distinct_id), person_properties={"email": user.email}, only_evaluate_locally=True
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
