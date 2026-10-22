from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_modeling.backend.logic.incremental_windows import WindowSpan, initial_span

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
