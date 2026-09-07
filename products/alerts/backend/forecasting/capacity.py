import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot, RateLimit
from posthog.settings import TEST

# Conservative launch limits for CPU-heavy synchronous fits. Saturation is recorded by
# RateLimit, so these can be tuned from production data without changing the API contract.
FORECAST_SIMULATION_GLOBAL_CONCURRENCY = 8
FORECAST_SIMULATION_TEAM_CONCURRENCY = 2
_SLOT_TTL_SECONDS = 5 * 60

__GLOBAL_LIMITER: RateLimit | None = None
__TEAM_LIMITER: RateLimit | None = None


class ForecastSimulationCapacityExceeded(Exception):
    pass


def _get_global_limiter() -> RateLimit:
    global __GLOBAL_LIMITER
    if __GLOBAL_LIMITER is None:
        __GLOBAL_LIMITER = RateLimit(
            max_concurrency=FORECAST_SIMULATION_GLOBAL_CONCURRENCY,
            limit_name="forecast_simulation_global",
            get_task_name=lambda *args, **kwargs: "alerts:forecast-simulation:global",
            get_task_id=lambda *args, **kwargs: kwargs["request_id"],
            ttl=_SLOT_TTL_SECONDS,
            apply_clickhouse_kill_switch=False,
            allow_team_bypass=False,
        )
    return __GLOBAL_LIMITER


def _get_team_limiter() -> RateLimit:
    global __TEAM_LIMITER
    if __TEAM_LIMITER is None:
        __TEAM_LIMITER = RateLimit(
            max_concurrency=FORECAST_SIMULATION_TEAM_CONCURRENCY,
            limit_name="forecast_simulation_per_team",
            get_task_name=lambda *args, **kwargs: "alerts:forecast-simulation:per-team",
            get_task_key=lambda *args, **kwargs: f"alerts:forecast-simulation:per-team:{kwargs['team_id']}",
            get_task_id=lambda *args, **kwargs: kwargs["request_id"],
            ttl=_SLOT_TTL_SECONDS,
            apply_clickhouse_kill_switch=False,
            allow_team_bypass=False,
        )
    return __TEAM_LIMITER


@contextmanager
def forecast_simulation_slot(*, team_id: int) -> Iterator[None]:
    """Limit the full query-and-fit simulation, globally and per team."""
    if TEST:
        yield
        return

    request_id = uuid.uuid4().hex
    global_limiter = _get_global_limiter()
    team_limiter = _get_team_limiter()
    global_slot: ConcurrencySlot | None = None
    team_slot: ConcurrencySlot | None = None

    try:
        try:
            global_slot = global_limiter.use(team_id=team_id, request_id=request_id)
        except ConcurrencyLimitExceeded:
            raise ForecastSimulationCapacityExceeded from None

        try:
            team_slot = team_limiter.use(team_id=team_id, request_id=request_id)
        except ConcurrencyLimitExceeded:
            raise ForecastSimulationCapacityExceeded from None

        yield
    finally:
        if team_slot is not None:
            with suppress(Exception):
                team_limiter.release(team_slot)
        if global_slot is not None:
            with suppress(Exception):
                global_limiter.release(global_slot)
