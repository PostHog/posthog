import uuid
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot, RateLimit
from posthog.settings import TEST

# Conservative launch limits for CPU-heavy synchronous fits. Saturation is recorded by
# RateLimit, so these can be tuned from production data without changing the API contract.
FORECAST_SIMULATION_GLOBAL_CONCURRENCY = 8
FORECAST_SIMULATION_TEAM_CONCURRENCY = 2
# Scheduled evaluations hold a budget of their own. Preview traffic arrives in bursts from the
# web tier, and a due alert that loses a slot waits a full cadence, so the two workloads must not
# draw on one pool.
FORECAST_EVALUATION_GLOBAL_CONCURRENCY = 8
FORECAST_EVALUATION_TEAM_CONCURRENCY = 2
_SLOT_TTL_SECONDS = 5 * 60

_SIMULATION_POOL = "simulation"
_EVALUATION_POOL = "evaluation"

__GLOBAL_LIMITERS: dict[str, RateLimit] = {}
__TEAM_LIMITERS: dict[str, RateLimit] = {}


class ForecastSimulationCapacityExceeded(Exception):
    pass


def _get_global_limiter(pool: str, max_concurrency: int) -> RateLimit:
    limiter = __GLOBAL_LIMITERS.get(pool)
    if limiter is None:
        limiter = RateLimit(
            max_concurrency=max_concurrency,
            limit_name=f"forecast_{pool}_global",
            get_task_name=lambda *args, **kwargs: f"alerts:forecast-{pool}:global",
            get_task_id=lambda *args, **kwargs: kwargs["request_id"],
            ttl=_SLOT_TTL_SECONDS,
            apply_clickhouse_kill_switch=False,
            allow_team_bypass=False,
        )
        __GLOBAL_LIMITERS[pool] = limiter
    return limiter


def _get_team_limiter(pool: str, max_concurrency: int) -> RateLimit:
    limiter = __TEAM_LIMITERS.get(pool)
    if limiter is None:
        limiter = RateLimit(
            max_concurrency=max_concurrency,
            limit_name=f"forecast_{pool}_per_team",
            get_task_name=lambda *args, **kwargs: f"alerts:forecast-{pool}:per-team",
            get_task_key=lambda *args, **kwargs: f"alerts:forecast-{pool}:per-team:{kwargs['team_id']}",
            get_task_id=lambda *args, **kwargs: kwargs["request_id"],
            ttl=_SLOT_TTL_SECONDS,
            apply_clickhouse_kill_switch=False,
            allow_team_bypass=False,
        )
        __TEAM_LIMITERS[pool] = limiter
    return limiter


@contextmanager
def _forecast_slot(*, team_id: int, pool: str, global_concurrency: int, team_concurrency: int) -> Iterator[None]:
    """Hold one slot in ``pool``, globally and per team, or raise ForecastSimulationCapacityExceeded."""
    if TEST:
        yield
        return

    request_id = uuid.uuid4().hex
    global_limiter = _get_global_limiter(pool, global_concurrency)
    team_limiter = _get_team_limiter(pool, team_concurrency)
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


@contextmanager
def forecast_simulation_slot(*, team_id: int) -> Iterator[None]:
    """Limit the full query-and-fit simulation behind a preview, globally and per team."""
    with _forecast_slot(
        team_id=team_id,
        pool=_SIMULATION_POOL,
        global_concurrency=FORECAST_SIMULATION_GLOBAL_CONCURRENCY,
        team_concurrency=FORECAST_SIMULATION_TEAM_CONCURRENCY,
    ):
        yield


@contextmanager
def forecast_evaluation_slot(*, team_id: int) -> Iterator[bool]:
    """Limit a scheduled fit against its own pool, without making saturation retryable.

    Scheduled checks never draw on the preview budget, so a burst of previews cannot take the slot
    a due alert needs. A preview should tell its caller to retry, while a scheduled check should be
    inconclusive and wait for its next normal cadence. Returning a flag lets the dispatcher skip
    both the query and the fit without turning capacity pressure into a Temporal retry storm.
    """
    with ExitStack() as stack:
        try:
            stack.enter_context(
                _forecast_slot(
                    team_id=team_id,
                    pool=_EVALUATION_POOL,
                    global_concurrency=FORECAST_EVALUATION_GLOBAL_CONCURRENCY,
                    team_concurrency=FORECAST_EVALUATION_TEAM_CONCURRENCY,
                )
            )
        except ForecastSimulationCapacityExceeded:
            yield False
            return
        yield True
