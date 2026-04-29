import datetime as dt
from collections.abc import Callable, Generator
from typing import Any, Protocol, runtime_checkable

from posthog.schema import DateRange

from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.hogql_queries.utils.query_date_range import QueryDateRange


class _HasResults(Protocol):
    results: Any


@runtime_checkable
class TimeSliceableRunner(Protocol):
    """Protocol for runners that support time-sliced execution."""

    @property
    def query_date_range(self) -> QueryDateRange: ...

    @property
    def query(self) -> Any: ...

    def run(self, execution_mode: ExecutionMode, **kwargs: Any) -> _HasResults: ...


def time_sliced_results(
    runner: TimeSliceableRunner,
    order_by_earliest: bool,
    make_runner: Callable[[DateRange], TimeSliceableRunner],
    analytics_props: Any = None,
) -> Generator[Any, None, None]:
    """
    A generator that yields results by splitting the query into progressive time slices.

    Instead of scanning the full date range, we fetch progressively larger slices:
        - first 3 minutes
        - then 1 hour
        - then 6 hours
        - then the remainder

    Most queries hit the limit within the first 3 minutes, avoiding a full scan.
    The limit is read from runner.query.limit.
    """
    limit = runner.query.limit or 0
    qdr = runner.query_date_range
    date_range_length = qdr.date_to() - qdr.date_from()

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

    if date_range_length > dt.timedelta(minutes=20):
        recent_runner, runner = runner_slice(runner, dt.timedelta(minutes=3))
        response = recent_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS, analytics_props=analytics_props)
        limit -= len(response.results)
        yield from response.results
        if limit <= 0:
            return
        runner.query.limit = limit

    if date_range_length > dt.timedelta(hours=4):
        recent_runner, runner = runner_slice(runner, dt.timedelta(minutes=60))
        response = recent_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS, analytics_props=analytics_props)
        limit -= len(response.results)
        yield from response.results
        if limit <= 0:
            return
        runner.query.limit = limit

    if date_range_length > dt.timedelta(hours=24):
        recent_runner, runner = runner_slice(runner, dt.timedelta(hours=6))
        response = recent_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS, analytics_props=analytics_props)
        limit -= len(response.results)
        yield from response.results
        if limit <= 0:
            return
        runner.query.limit = limit

    response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS, analytics_props=analytics_props)
    yield from response.results
