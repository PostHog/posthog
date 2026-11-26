from datetime import timedelta
from typing import Any, Literal

from posthog.dataclasses import frozen

from products.ai_observability.backend.models.evaluation_configs import (
    DEFAULT_SETTLE_STRATEGY_BY_TARGET,
    SESSION_EVAL_DEFAULT_MAX_AGE_SECONDS,
    SESSION_EVAL_DEFAULT_QUIET_PERIOD_SECONDS,
    SESSION_EVAL_DEFAULT_WINDOW_SECONDS,
    SESSION_EVAL_MAX_MAX_AGE_SECONDS,
    SESSION_EVAL_MAX_QUIET_PERIOD_SECONDS,
    SESSION_EVAL_MAX_WINDOW_SECONDS,
    SESSION_EVAL_MIN_MAX_AGE_SECONDS,
    SESSION_EVAL_MIN_QUIET_PERIOD_SECONDS,
    SESSION_EVAL_MIN_WINDOW_SECONDS,
    TRACE_EVAL_DEFAULT_MAX_AGE_SECONDS,
    TRACE_EVAL_DEFAULT_QUIET_PERIOD_SECONDS,
    TRACE_EVAL_DEFAULT_WINDOW_SECONDS,
    TRACE_EVAL_MAX_MAX_AGE_SECONDS,
    TRACE_EVAL_MAX_QUIET_PERIOD_SECONDS,
    TRACE_EVAL_MAX_WINDOW_SECONDS,
    TRACE_EVAL_MIN_MAX_AGE_SECONDS,
    TRACE_EVAL_MIN_QUIET_PERIOD_SECONDS,
    TRACE_EVAL_MIN_WINDOW_SECONDS,
)
from products.ai_observability.backend.models.evaluations import EvaluationTarget

INGESTION_LAG_MARGIN_SECONDS = 15


def _clamp(value: Any, floor: int, ceiling: int, default: int) -> int:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return default
    return int(min(max(value, floor), ceiling))


# (floor, ceiling, default) per field, per target. The workflow re-clamps what the serializer
# already validated, so a payload written before a bound moved can never wedge the settle phase.
_SETTLE_BOUNDS: dict[str, dict[str, tuple[int, int, int]]] = {
    "trace": {
        "window": (TRACE_EVAL_MIN_WINDOW_SECONDS, TRACE_EVAL_MAX_WINDOW_SECONDS, TRACE_EVAL_DEFAULT_WINDOW_SECONDS),
        "quiet": (
            TRACE_EVAL_MIN_QUIET_PERIOD_SECONDS,
            TRACE_EVAL_MAX_QUIET_PERIOD_SECONDS,
            TRACE_EVAL_DEFAULT_QUIET_PERIOD_SECONDS,
        ),
        "max_age": (TRACE_EVAL_MIN_MAX_AGE_SECONDS, TRACE_EVAL_MAX_MAX_AGE_SECONDS, TRACE_EVAL_DEFAULT_MAX_AGE_SECONDS),
    },
    "session": {
        "window": (
            SESSION_EVAL_MIN_WINDOW_SECONDS,
            SESSION_EVAL_MAX_WINDOW_SECONDS,
            SESSION_EVAL_DEFAULT_WINDOW_SECONDS,
        ),
        "quiet": (
            SESSION_EVAL_MIN_QUIET_PERIOD_SECONDS,
            SESSION_EVAL_MAX_QUIET_PERIOD_SECONDS,
            SESSION_EVAL_DEFAULT_QUIET_PERIOD_SECONDS,
        ),
        "max_age": (
            SESSION_EVAL_MIN_MAX_AGE_SECONDS,
            SESSION_EVAL_MAX_MAX_AGE_SECONDS,
            SESSION_EVAL_DEFAULT_MAX_AGE_SECONDS,
        ),
    },
}


@frozen
class SettlePlan:
    strategy: Literal["inactivity", "fixed_window"]
    # The quiet period under inactivity, the window under fixed_window.
    primary_seconds: int
    max_age_seconds: int


def resolve_settle_plan(settle: dict[str, Any] | None, target: str = "trace") -> SettlePlan:
    """Resolve the settle config into a SettlePlan.

    Deterministic and exception-free on purpose: the serializer already validated the stored
    config, so anything malformed here is a payload bug — falling back to defaults keeps a bad
    payload from wedging the workflow. max_age is coerced to cover at least one quiet period.
    """
    bounds = _SETTLE_BOUNDS.get(target, _SETTLE_BOUNDS["trace"])
    config = settle or {}
    strategy = config.get("strategy") or DEFAULT_SETTLE_STRATEGY_BY_TARGET.get(target, "fixed_window")
    if strategy == "inactivity":
        quiet = _clamp(config.get("quiet_period_seconds"), *bounds["quiet"])
        max_age = _clamp(config.get("max_age_seconds"), *bounds["max_age"])
        return SettlePlan(strategy="inactivity", primary_seconds=quiet, max_age_seconds=max(max_age, quiet))
    window = _clamp(config.get("window_seconds"), *bounds["window"])
    return SettlePlan(strategy="fixed_window", primary_seconds=window, max_age_seconds=window)


def settle_horizon(target: str, settle: dict[str, Any] | None) -> timedelta:
    """How long after its first event a unit is still being graded by the live path.

    Zero for a generation, which is complete when it lands. For a trace or a session it is the
    settle ceiling the evaluation is configured with, which reaches 7 days for a session, not the
    24 hour default. Two things read it: the window a backfill may cover, and how far past that
    window a live verdict for one of its units can still be stamped.
    """
    if target == EvaluationTarget.GENERATION.value:
        return timedelta(0)
    plan = resolve_settle_plan(settle, target)
    return timedelta(seconds=plan.max_age_seconds + INGESTION_LAG_MARGIN_SECONDS)
