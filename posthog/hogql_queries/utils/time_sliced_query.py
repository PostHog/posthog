import math
import time
import random
import datetime as dt
from collections.abc import Callable, Generator
from dataclasses import field
from typing import Any, Protocol, runtime_checkable

from posthog.schema import DateRange

from posthog.dataclasses import frozen
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryTimeOut
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

# One request walks up to four slices, so this budget has to be shared rather than granted per
# slice. A per-slice grant lets one request spend four times this much ClickHouse time and run past
# the gateway timeout. The value matches HogQLGlobalSettings.max_execution_time.
DEFAULT_BUDGET_SECONDS = 60.0

# ClickHouse refuses a query over its concurrency limit in tens of milliseconds, before it reads
# anything, so the slice can be re-sent cheaply. The retry only has to outlast a burst of concurrent
# queries, and the budget caps it either way.
CAPACITY_RETRY_ATTEMPTS = 3
CAPACITY_RETRY_BASE_DELAY = 0.25


class _HasResults(Protocol):
    results: Any


@runtime_checkable
class TimeSliceableRunner(Protocol):
    """Protocol for runners that support time-sliced execution."""

    @property
    def query_date_range(self) -> QueryDateRange: ...

    @property
    def query(self) -> Any: ...

    def set_execution_time_budget(self, seconds: int) -> None: ...

    def run(self, execution_mode: ExecutionMode, **kwargs: Any) -> _HasResults: ...


@frozen(frozen=False)
class TimeSliceBudget:
    """The wall-clock time one request may spend across all of its slices.

    `truncated` reports that the ladder stopped before it read the whole date range, so the caller
    can tell the client there is more to page through.
    """

    seconds: float = DEFAULT_BUDGET_SECONDS
    truncated: bool = False
    started_at: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self.started_at = time.monotonic()

    def remaining(self) -> float:
        return self.seconds - (time.monotonic() - self.started_at)


def time_sliced_results(
    runner: TimeSliceableRunner,
    order_by_earliest: bool,
    make_runner: Callable[[DateRange], TimeSliceableRunner],
    analytics_props: Any = None,
    budget: TimeSliceBudget | None = None,
) -> Generator[Any]:
    """
    A generator that yields results by splitting the query into progressive time slices.

    Instead of scanning the full date range, we fetch progressively larger slices:
        - first 3 minutes
        - then 1 hour
        - then 6 hours
        - then the remainder

    Most queries hit the limit within the first 3 minutes, avoiding a full scan.
    The limit is read from runner.query.limit.

    Every slice draws on one shared `budget`. When it runs out, the generator stops and marks the
    budget truncated rather than starting another slice.
    """
    limit = runner.query.limit or 0
    qdr = runner.query_date_range
    date_range_length = qdr.date_to() - qdr.date_from()
    budget = budget if budget is not None else TimeSliceBudget()
    produced_any = False

    def runner_slice(
        current_runner: TimeSliceableRunner, slice_length: dt.timedelta
    ) -> tuple[TimeSliceableRunner, TimeSliceableRunner]:
        """
        Splits a runner into two: one for the slice closest to the sort edge,
        and one for the remainder.
        """
        current_qdr = current_runner.query_date_range
        if not order_by_earliest:
            slice_date_range = DateRange(
                date_from=(current_qdr.date_to() - slice_length).isoformat(),
                date_to=current_qdr.date_to().isoformat(),
            )
            remainder_date_range = DateRange(
                date_from=current_qdr.date_from().isoformat(),
                date_to=(current_qdr.date_to() - slice_length).isoformat(),
            )
        else:
            slice_date_range = DateRange(
                date_from=current_qdr.date_from().isoformat(),
                date_to=(current_qdr.date_from() + slice_length).isoformat(),
            )
            remainder_date_range = DateRange(
                date_from=(current_qdr.date_from() + slice_length).isoformat(),
                date_to=current_qdr.date_to().isoformat(),
            )

        return make_runner(slice_date_range), make_runner(remainder_date_range)

    def give_up(error: Exception) -> None:
        """Rows already yielded beat the rest of the range, so keep them and let the cursor go on.

        With nothing yielded there is nothing to keep, and the caller must still see the error.
        """
        if not produced_any:
            raise error
        budget.truncated = True

    def run_slice(slice_runner: TimeSliceableRunner) -> _HasResults | None:
        """Runs one slice inside the shared budget, or returns None once the budget is spent."""
        for attempt in range(CAPACITY_RETRY_ATTEMPTS):
            remaining = budget.remaining()
            if remaining <= 0:
                give_up(ClickHouseQueryTimeOut())
                return None
            slice_runner.set_execution_time_budget(max(1, math.ceil(remaining)))
            try:
                return slice_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS, analytics_props=analytics_props)
            except ClickHouseQueryTimeOut as error:
                # The slice spent the budget, so a retry has nothing left to run in.
                give_up(error)
                return None
            except ClickHouseAtCapacity as error:
                if attempt == CAPACITY_RETRY_ATTEMPTS - 1:
                    give_up(error)
                    return None
                delay = CAPACITY_RETRY_BASE_DELAY * 2**attempt * random.uniform(0.5, 1.5)
                time.sleep(max(0.0, min(delay, budget.remaining())))
        return None

    for threshold, slice_length in (
        (dt.timedelta(minutes=20), dt.timedelta(minutes=3)),
        (dt.timedelta(hours=4), dt.timedelta(minutes=60)),
        (dt.timedelta(hours=24), dt.timedelta(hours=6)),
    ):
        if date_range_length <= threshold:
            continue
        recent_runner, runner = runner_slice(runner, slice_length)
        response = run_slice(recent_runner)
        if response is None:
            return
        limit -= len(response.results)
        produced_any = produced_any or bool(response.results)
        yield from response.results
        if limit <= 0:
            return
        runner.query.limit = limit

    response = run_slice(runner)
    if response is None:
        return
    yield from response.results
