import uuid
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress

from redis.exceptions import RedisError

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot, RateLimit
from posthog.settings import TEST
from posthog.temporal.common.errors import NonReportableError

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


class ForecastEvaluationCapacityExceeded(NonReportableError):
    """Scheduled forecast capacity is full, so the next sweep must retry the due check.

    Saturation is a limiter decision the pool is designed to make, and RateLimit already records
    it. The activity interceptor reports every other exception to error tracking on each attempt,
    so without the NonReportableError marker one full pool mints an event per retry for every due
    forecast alert, which is loudest exactly when the system is busiest.
    """


class ForecastCapacityUnavailable(Exception):
    """The capacity store could not be reached, so no slot decision was made.

    Different from saturation: nothing says the pool is full, only that the limiter is unreachable.
    Callers must treat it as a transient infrastructure failure and retry, because running the fit
    anyway would drop the concurrency ceiling exactly when the store is unhealthy.
    """


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
    """Hold one slot in ``pool``, globally and per team, or raise ForecastSimulationCapacityExceeded.

    A store that cannot be reached raises ForecastCapacityUnavailable instead, so an outage is never
    read as a full pool.
    """
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
        except RedisError as err:
            raise ForecastCapacityUnavailable(str(err)) from err

        try:
            team_slot = team_limiter.use(team_id=team_id, request_id=request_id)
        except ConcurrencyLimitExceeded:
            raise ForecastSimulationCapacityExceeded from None
        except RedisError as err:
            raise ForecastCapacityUnavailable(str(err)) from err

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
def forecast_evaluation_slot(*, team_id: int) -> Iterator[None]:
    """Limit a scheduled fit against its own pool and surface saturation as retryable.

    Scheduled checks never draw on the preview budget, so a burst of previews cannot take the slot
    a due alert needs. A saturated scheduled check must not write an inconclusive result because
    that advances ``next_check_at`` by a full cadence. The workflow retries briefly, then leaves the
    alert overdue for the next one-minute sweep.

    An unreachable store is not capacity pressure, so ForecastCapacityUnavailable propagates to the
    caller's retry policy rather than spending the alert's cadence on a failed slot lookup.
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
        except ForecastSimulationCapacityExceeded as error:
            raise ForecastEvaluationCapacityExceeded from error
        yield
