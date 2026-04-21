import datetime as dt
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

from unittest import TestCase
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import DateRange

from posthog.hogql_queries.utils.time_sliced_query import time_sliced_results


@dataclass
class FakeDateRange:
    _date_from: dt.datetime
    _date_to: dt.datetime

    def date_from(self) -> dt.datetime:
        return self._date_from

    def date_to(self) -> dt.datetime:
        return self._date_to


@dataclass
class FakeQuery:
    dateRange: DateRange
    limit: int | None = None


@dataclass
class FakeResponse:
    results: list[Any] = field(default_factory=list)


class FakeRunner:
    """Minimal runner that satisfies the interface expected by time_sliced_results."""

    def __init__(
        self, date_from: dt.datetime, date_to: dt.datetime, results: list[Any] | None = None, limit: int = 100
    ):
        self.query = FakeQuery(
            dateRange=DateRange(date_from=date_from.isoformat(), date_to=date_to.isoformat()), limit=limit
        )
        self._query_date_range = FakeDateRange(date_from, date_to)
        self._results = results or []

    @property
    def query_date_range(self) -> Any:
        return self._query_date_range

    def run(self, execution_mode: Any, **kwargs: Any) -> FakeResponse:
        return FakeResponse(results=self._results)


class TestTimeSlicedResults(TestCase):
    def _make_runner_factory(self, results_per_call: list[list[Any]]):
        """Returns a make_runner callable that tracks created date ranges and returns canned results."""
        call_index = [0]
        created_ranges: list[DateRange] = []

        def make_runner(date_range: DateRange) -> FakeRunner:
            idx = call_index[0]
            call_index[0] += 1
            created_ranges.append(date_range)
            results = results_per_call[idx] if idx < len(results_per_call) else []
            fr = FakeRunner(
                date_from=dt.datetime.fromisoformat(date_range.date_from).replace(tzinfo=ZoneInfo("UTC"))
                if date_range.date_from
                else dt.datetime.now(tz=ZoneInfo("UTC")),
                date_to=dt.datetime.fromisoformat(date_range.date_to).replace(tzinfo=ZoneInfo("UTC"))
                if date_range.date_to
                else dt.datetime.now(tz=ZoneInfo("UTC")),
                results=results,
            )
            return fr

        return make_runner, created_ranges

    def test_small_range_no_slicing(self):
        now = dt.datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
        runner = FakeRunner(
            date_from=now - dt.timedelta(minutes=10),
            date_to=now,
            results=["a", "b", "c"],
        )
        make_runner, created_ranges = self._make_runner_factory([])

        results = list(time_sliced_results(runner, order_by_earliest=False, make_runner=make_runner))

        self.assertEqual(results, ["a", "b", "c"])
        # No slicing should have been done — make_runner never called
        self.assertEqual(len(created_ranges), 0)

    def test_medium_range_one_slice(self):
        now = dt.datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
        runner = FakeRunner(
            date_from=now - dt.timedelta(hours=1),
            date_to=now,
            results=["initial_not_used"],
        )
        # make_runner called twice: slice (3 min) + remainder
        # The remainder runner is the one that gets run for the final fetch
        make_runner, created_ranges = self._make_runner_factory(
            [
                ["a", "b"],  # 3-min slice
                ["c"],  # remainder (final runner that gets run)
            ]
        )

        results = list(time_sliced_results(runner, order_by_earliest=False, make_runner=make_runner))

        self.assertEqual(results, ["a", "b", "c"])
        self.assertEqual(len(created_ranges), 2)

    def test_large_range_all_slices(self):
        now = dt.datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
        runner = FakeRunner(
            date_from=now - dt.timedelta(days=2),
            date_to=now,
            results=[],
        )
        # 3 slice levels: 3min, 1hr, 6hr — each creates a slice + remainder pair
        # The last remainder is the one that gets run for the final fetch
        make_runner, created_ranges = self._make_runner_factory(
            [
                ["a"],  # 3-min slice
                [],  # 3-min remainder (becomes input for next slice)
                ["b"],  # 1-hr slice
                [],  # 1-hr remainder (becomes input for next slice)
                ["c"],  # 6-hr slice
                ["d"],  # 6-hr remainder (final runner that gets run)
            ]
        )

        results = list(time_sliced_results(runner, order_by_earliest=False, make_runner=make_runner))

        self.assertEqual(results, ["a", "b", "c", "d"])
        self.assertEqual(len(created_ranges), 6)

    def test_stops_when_limit_reached_first_slice(self):
        now = dt.datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
        runner = FakeRunner(
            date_from=now - dt.timedelta(hours=1),
            date_to=now,
            results=[],
            limit=3,
        )
        make_runner, created_ranges = self._make_runner_factory(
            [
                ["a", "b", "c"],  # 3-min slice fills limit
                [],  # remainder (created but never run)
            ]
        )

        results = list(time_sliced_results(runner, order_by_earliest=False, make_runner=make_runner))

        self.assertEqual(results, ["a", "b", "c"])

    def test_stops_when_limit_reached_second_slice(self):
        now = dt.datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
        runner = FakeRunner(
            date_from=now - dt.timedelta(hours=5),
            date_to=now,
            results=[],
            limit=3,
        )
        make_runner, created_ranges = self._make_runner_factory(
            [
                ["a"],  # 3-min slice
                [],  # 3-min remainder
                ["b", "c"],  # 1-hr slice fills limit
                [],  # 1-hr remainder
            ]
        )

        results = list(time_sliced_results(runner, order_by_earliest=False, make_runner=make_runner))

        self.assertEqual(results, ["a", "b", "c"])

    @parameterized.expand(
        [
            ("latest", False),
            ("earliest", True),
        ]
    )
    def test_slice_direction(self, _name, order_by_earliest):
        now = dt.datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
        date_from = now - dt.timedelta(hours=1)
        runner = FakeRunner(date_from=date_from, date_to=now, results=[])

        make_runner, created_ranges = self._make_runner_factory(
            [
                ["a"],  # slice
                ["b"],  # remainder
            ]
        )

        list(time_sliced_results(runner, order_by_earliest=order_by_earliest, make_runner=make_runner))

        self.assertEqual(len(created_ranges), 2)
        slice_range = created_ranges[0]
        remainder_range = created_ranges[1]

        if order_by_earliest:
            # Slice should be at the start of the range
            self.assertEqual(slice_range.date_from, date_from.isoformat())
            # Remainder should be after the slice
            self.assertEqual(remainder_range.date_to, now.isoformat())
        else:
            # Slice should be at the end of the range
            self.assertEqual(slice_range.date_to, now.isoformat())
            # Remainder should be before the slice
            self.assertEqual(remainder_range.date_from, date_from.isoformat())

    def test_analytics_props_passed_through(self):
        now = dt.datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
        run_mock = MagicMock(return_value=FakeResponse(results=["a"]))
        runner = FakeRunner(date_from=now - dt.timedelta(minutes=5), date_to=now, results=["a"])
        runner.run = run_mock  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]

        make_runner, _ = self._make_runner_factory([])
        props = {"source": "test"}

        list(time_sliced_results(runner, order_by_earliest=False, make_runner=make_runner, analytics_props=props))

        run_mock.assert_called_once()
        _, kwargs = run_mock.call_args
        self.assertEqual(kwargs["analytics_props"], props)
