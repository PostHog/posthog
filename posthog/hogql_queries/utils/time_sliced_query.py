import datetime as dt
from collections.abc import Callable, Generator
from typing import Any

from posthog.schema import DateRange

from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode


def time_sliced_results(
    runner: AnalyticsQueryRunner,
    limit: int,
    order_by_earliest: bool,
    make_runner: Callable[[DateRange], AnalyticsQueryRunner],
    analytics_props: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    """
    A generator that yields results by splitting the query into progressive time slices.

    Instead of scanning the full date range, we fetch progressively larger slices:
        - first 3 minutes
        - then 1 hour
        - then 6 hours
        - then the remainder

    Most queries hit the limit within the first 3 minutes, avoiding a full scan.
    """
    qdr = runner.query_date_range
    date_range_length = qdr.date_to() - qdr.date_from()

    def runner_slice(
        current_runner: AnalyticsQueryRunner, slice_length: dt.timedelta
    ) -> tuple[AnalyticsQueryRunner, AnalyticsQueryRunner]:
        """
        Splits a runner into two: one for the slice closest to the sort edge,
        and one for the remainder.
        """
        if not order_by_earliest:
            slice_date_range = DateRange(
                date_from=(current_runner.query_date_range.date_to() - slice_length).isoformat(),
                date_to=current_runner.query_date_range.date_to().isoformat(),
            )
            remainder_date_range = DateRange(
                date_from=current_runner.query_date_range.date_from().isoformat(),
                date_to=(current_runner.query_date_range.date_to() - slice_length).isoformat(),
            )
        else:
            slice_date_range = DateRange(
                date_from=current_runner.query_date_range.date_from().isoformat(),
                date_to=(current_runner.query_date_range.date_from() + slice_length).isoformat(),
            )
            remainder_date_range = DateRange(
                date_from=(current_runner.query_date_range.date_from() + slice_length).isoformat(),
                date_to=current_runner.query_date_range.date_to().isoformat(),
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
