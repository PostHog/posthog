import math
from datetime import datetime, timedelta

from django.utils import timezone

from scipy.stats import chisquare

from posthog.dataclasses import frozen

from ..facade.enums import IdeaOutcome

MIN_SAMPLES_PER_VARIANT = 50
SPLIT_P_VALUE = 0.001
MAX_MIXED_SHARE = 0.1


@frozen
class Verdict:
    outcome: IdeaOutcome | None
    variant: str
    note: str
    facts: dict


def waiting(variant: str, note: str, facts: dict) -> Verdict:
    return Verdict(outcome=None, variant=variant, note=note, facts=facts)


def decided(outcome: IdeaOutcome, variant: str, note: str, facts: dict) -> Verdict:
    return Verdict(outcome=outcome, variant=variant, note=note, facts=facts)


def interval(row: dict) -> tuple[float, float] | None:
    values = row.get("credible_interval") or row.get("confidence_interval") or []
    if len(values) != 2 or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
        return None
    low, high = float(values[0]), float(values[1])
    return (low, high) if low <= high else None


def _matches(name: str, wanted: str) -> bool:
    ordinal, separator, rest = name.partition(". ")
    return name == wanted or bool(separator and ordinal.isdecimal() and rest == wanted)


def verdict(
    evidence: dict,
    *,
    direction: str,
    guardrails: list[dict],
    run_days: int,
    exposed_at: datetime | None = None,
    now: datetime | None = None,
) -> Verdict:
    results = evidence.get("results") or {}
    exposures: dict = results.get("exposures") or {}
    tests = sorted(key for key in set(results.get("variants") or exposures) - {"control"} if not key.startswith("$"))
    started = evidence.get("start_date")
    facts = {"exposures": exposures, "start_date": started}
    if not started:
        return waiting("", "The experiment has not started.", facts)
    if not exposures or not sum(exposures.values()):
        return waiting("", "Waiting for the first people to see it.", facts)
    samples = results.get("metric_sample_counts") or []
    smallest = min((counts.get(key, 0) for counts in samples for key in [*tests, "control"]), default=0)
    facts["smallest_sample"] = smallest
    rows = {
        row["key"]: row
        for metric in (results.get("primary_metrics_results") or [])[:1]
        for row in metric.get("variant_results", [])
    }
    primary = {key: interval(rows.get(key, {})) for key in tests}
    facts["primary"] = {key: list(value) if value else None for key, value in primary.items()}
    harmed: list[str] = []
    for guard in guardrails:
        metric = next(
            (
                item
                for item in results.get("secondary_metrics_results") or []
                if _matches(item.get("name", ""), guard["name"])
            ),
            None,
        )
        for row in (metric or {}).get("variant_results", []):
            bounds = interval(row)
            limit = float(guard.get("max_regression", 0.05))
            if bounds is None or row.get("key") == "control":
                continue
            if guard.get("direction", "increase") == "decrease" and bounds[0] > limit:
                harmed.append(guard["name"])
            if guard.get("direction", "increase") == "increase" and bounds[1] < -limit:
                harmed.append(guard["name"])
    facts["harmed_guardrails"] = sorted(set(harmed))
    if smallest < MIN_SAMPLES_PER_VARIANT:
        return waiting(
            "", f"Collecting data: {smallest} of {MIN_SAMPLES_PER_VARIANT} people in the smallest group.", facts
        )
    arms = ["control", *tests]
    counts = [float(exposures.get(key, 0)) for key in arms]
    if len(counts) > 1 and chisquare(counts).pvalue < SPLIT_P_VALUE:
        split = ", ".join(f"{key} {int(count)}" for key, count in zip(arms, counts))
        return decided(
            IdeaOutcome.DROPPED,
            "control",
            f"The variants got uneven traffic ({split}). The change may be broken. Check the build before you try it again.",
            facts,
        )
    mixed = float(exposures.get("$multiple", 0))
    if mixed > MAX_MIXED_SHARE * sum(float(value) for value in exposures.values()):
        return decided(
            IdeaOutcome.DROPPED,
            "control",
            f"{int(mixed)} people saw more than one variant, so the result is not reliable. The flag code may read the variant too early. Check the build before you try it again.",
            facts,
        )
    if harmed:
        return decided(IdeaOutcome.HARMED, "control", f"{', '.join(sorted(set(harmed)))} got worse.", facts)
    elapsed = (now or timezone.now()) - (exposed_at or datetime.fromisoformat(started))
    left = timedelta(days=run_days) - elapsed
    if left > timedelta(0):
        days_left = math.ceil(left.total_seconds() / 86400)
        return waiting("", f"About {days_left} more {'day' if days_left == 1 else 'days'} before a verdict.", facts)
    better = [
        key
        for key, value in primary.items()
        if value and rows[key].get("significant") and (value[1] < 0 if direction == "decrease" else value[0] > 0)
    ]
    worse = [
        key
        for key, value in primary.items()
        if value and rows[key].get("significant") and (value[0] > 0 if direction == "decrease" else value[1] < 0)
    ]
    if better:
        best = max(better, key=lambda key: abs(sum(primary[key] or (0, 0))))
        return decided(IdeaOutcome.WON, best, f"The {best} variant improved the primary metric.", facts)
    if tests and len(worse) == len(tests):
        return decided(IdeaOutcome.LOST, "control", "Every test variant made the primary metric worse.", facts)
    return decided(IdeaOutcome.FLAT, "control", f"No clear effect after {run_days} days.", facts)
