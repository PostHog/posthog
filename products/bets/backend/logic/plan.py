import math
import datetime
from statistics import fmean

from posthog.dataclasses import frozen

MIN_OBSERVATIONS = 300
MIN_DAYS = 2
MAX_DAYS = 28
DRIFT = 1.5
WEEKLY_SPREAD = 0.3
Z_FACTOR = 16
GROUPS = 2
EXPOSURE_GRACE = datetime.timedelta(hours=48)


@frozen
class Readiness:
    ready: bool
    note: str


@frozen
class Spread:
    mean: float
    variance: float


@frozen
class Plan:
    days: int
    mde: float
    audience: int
    weekly: bool
    too_long: bool


def readiness(observed: int, days: float) -> Readiness:
    if observed >= MIN_OBSERVATIONS and days >= MIN_DAYS:
        return Readiness(ready=True, note="")
    rate = observed / days if days > 0 else 0
    left_for_data = (MIN_OBSERVATIONS - observed) / rate if rate else None
    left = max(left_for_data or 0, MIN_DAYS - days)
    eta = f" About {math.ceil(left)} more days." if left_for_data is not None or observed >= MIN_OBSERVATIONS else ""
    return Readiness(
        ready=False, note=f"Collecting a baseline: {min(observed, MIN_OBSERVATIONS)} of {MIN_OBSERVATIONS}.{eta}"
    )


def estimated_spread(value: float) -> Spread:
    if 0 < value < 1:
        return Spread(mean=value, variance=value * (1 - value))
    mean = abs(value) or 1.0
    return Spread(mean=mean, variance=mean**2)


def control_spread(baseline: dict) -> Spread | None:
    samples = baseline.get("number_of_samples") or 0
    if samples <= 0:
        return None
    mean = float(baseline.get("sum") or 0) / samples
    variance = float(baseline.get("sum_squares") or 0) / samples - mean**2
    if mean <= 0 or variance <= 0:
        return None
    return Spread(mean=mean, variance=variance)


def weekly_pattern(values: list[float], dates: list[str]) -> bool:
    if len(values) < 14:
        return False
    by_day: dict[int, list[float]] = {}
    for value, date in zip(values, dates):
        by_day.setdefault(datetime.date.fromisoformat(date[:10]).weekday(), []).append(value)
    means = [fmean(day) for day in by_day.values() if day]
    overall = fmean(means) if means else 0
    return bool(overall) and (max(means) - min(means)) / abs(overall) > WEEKLY_SPREAD


def total_sample(spread: Spread, mde: float) -> int:
    effect = spread.mean * mde / 100
    return math.ceil(Z_FACTOR * spread.variance / effect**2) * GROUPS


def detectable_effect(spread: Spread, days: int, audience: int) -> float:
    per_group = days * audience / GROUPS
    return math.sqrt(Z_FACTOR * spread.variance / per_group) / spread.mean * 100


def plan(spread: Spread, *, mde: float, audience: int, weekly: bool, floor_days: int = 0) -> Plan:
    days = max(math.ceil(total_sample(spread, mde) / max(audience, 1)), MIN_DAYS, floor_days)
    if weekly:
        days = math.ceil(days / 7) * 7
    return Plan(days=days, mde=mde, audience=audience, weekly=weekly, too_long=days > MAX_DAYS)
