import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_modeling.backend.logic.incremental_windows import (
    WindowSpan,
    initial_span,
    search_lower_bound,
    skip_empty_ranges,
)

AUG_1 = datetime(2026, 8, 1, tzinfo=UTC)


class TestWindowSpans(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "datetime",
                AUG_1,
                AUG_1,
                WindowSpan(size=timedelta(days=1), minimum=timedelta(minutes=1), maximum=timedelta(days=32)),
            ),
            (
                "date",
                date(2026, 8, 1),
                date(2026, 8, 1),
                WindowSpan(size=timedelta(days=1), minimum=timedelta(days=1), maximum=timedelta(days=32)),
            ),
            ("integer_range", 0, 1600, WindowSpan(size=100, minimum=1, maximum=3200)),
            ("integer_range_rounds_up", 0, 17, WindowSpan(size=2, minimum=1, maximum=64)),
            ("integer_single_value", 7, 7, WindowSpan(size=1, minimum=1, maximum=32)),
            ("text", "a", "z", None),
            ("float", 0.5, 9.5, None),
        ]
    )
    def test_initial_span_follows_the_key_type(
        self, _name: str, key_min: Any, key_max: Any, expected: Optional[WindowSpan[Any]]
    ) -> None:
        assert initial_span(key_min, key_max) == expected

    def test_a_span_shrinks_to_its_minimum_and_grows_to_its_maximum(self) -> None:
        span = WindowSpan(size=timedelta(minutes=4), minimum=timedelta(minutes=1), maximum=timedelta(minutes=8))

        halved_once = span.halved()
        assert halved_once is not None and halved_once.size == timedelta(minutes=2)
        at_minimum = halved_once.halved()
        assert at_minimum is not None and at_minimum.size == timedelta(minutes=1)
        assert at_minimum.halved() is None

        assert span.grown().size == timedelta(minutes=8)
        assert span.grown().grown().size == timedelta(minutes=8)


class TestKeyRangeSearch(SimpleTestCase):
    @parameterized.expand(
        [
            ("ninety_days_of_history", timedelta(days=90), timedelta(days=128), 8),
            ("only_the_last_hours", timedelta(hours=6), timedelta(days=1), 1),
        ]
    )
    def test_the_lower_bound_is_the_first_doubling_with_nothing_below(
        self, _name: str, history: timedelta, expected_offset: timedelta, expected_checks: int
    ) -> None:
        oldest = AUG_1 - history
        checks: list[datetime] = []

        async def has_rows_below(bound: datetime) -> bool:
            checks.append(bound)
            return oldest < bound

        assert asyncio.run(search_lower_bound(has_rows_below, AUG_1)) == AUG_1 - expected_offset
        assert len(checks) == expected_checks

    def test_the_search_gives_up_past_its_doubling_limit(self) -> None:
        async def always(bound: datetime) -> bool:
            return True

        assert asyncio.run(search_lower_bound(always, AUG_1)) is None

    def test_an_empty_stretch_is_skipped_in_a_few_checks_without_passing_data(self) -> None:
        next_rows = AUG_1 + timedelta(days=7000)
        checks: list[tuple[datetime, datetime]] = []

        async def has_rows_between(since: datetime, until: datetime) -> bool:
            checks.append((since, until))
            return since <= next_rows < until

        start = asyncio.run(skip_empty_ranges(has_rows_between, AUG_1, timedelta(days=1), AUG_1 + timedelta(days=9000)))

        assert start <= next_rows
        assert checks[-1] == (start, checks[-1][1]) and checks[-1][0] <= next_rows < checks[-1][1]
        assert len(checks) <= 14

    def test_a_range_with_rows_right_away_is_not_skipped(self) -> None:
        async def has_rows_between(since: datetime, until: datetime) -> bool:
            return True

        assert (
            asyncio.run(skip_empty_ranges(has_rows_between, AUG_1, timedelta(days=1), AUG_1 + timedelta(days=90)))
            == AUG_1
        )
