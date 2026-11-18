from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.apm.backend.logic.health.dependencies import (
    CHILD_MARGIN,
    EXACT_SPAN_LIMIT,
    MAX_SAMPLE_SLICES,
    _plan_sample,
    _SpanDensity,
)

FROM = datetime(2026, 6, 2, 8, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)


def _even(window: timedelta, total: int) -> _SpanDensity:
    minutes = int(window / timedelta(minutes=1))
    return _SpanDensity.from_buckets(
        [(FROM + timedelta(minutes=i), total // minutes) for i in range(minutes)], MINUTE, FROM, FROM + window
    )


class TestPlanSample(SimpleTestCase):
    def test_window_under_the_limit_is_read_whole(self) -> None:
        self.assertIsNone(_plan_sample(_even(timedelta(hours=1), EXACT_SPAN_LIMIT), FROM, FROM + timedelta(hours=1)))

    @parameterized.expand(
        [
            ("hour_at_ten_times_the_limit", timedelta(hours=1), 10, 6),
            ("day_at_a_thousand_times_the_limit", timedelta(days=1), 1000, 1),
            ("day_just_over_the_limit", timedelta(days=1), 1.25, MAX_SAMPLE_SLICES),
        ]
    )
    def test_slices_with_their_margins_read_the_limit(
        self, _name: str, window: timedelta, overload: float, slices: int
    ) -> None:
        to = FROM + window
        sample = _plan_sample(_even(window, int(EXACT_SPAN_LIMIT * overload)), FROM, to)
        assert sample is not None
        self.assertEqual(len(sample.slices), slices)
        read = sum(
            (min(to, end + CHILD_MARGIN) - max(FROM, start - CHILD_MARGIN) for start, end in sample.slices),
            timedelta(0),
        )
        self.assertAlmostEqual(read / window, 1 / overload, places=3)
        self.assertTrue(all(FROM <= start < end <= to for start, end in sample.slices))
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(sample.slices, sample.slices[1:])))

    def test_burst_in_one_minute_gets_a_narrow_slice(self) -> None:
        # Twice the limit in the first minute of an hour and nothing after it: a third of that minute,
        # plus its child margin, holds the limit.
        to = FROM + timedelta(hours=1)
        sample = _plan_sample(_SpanDensity.from_buckets([(FROM, EXACT_SPAN_LIMIT * 2)], MINUTE, FROM, to), FROM, to)
        assert sample is not None
        start, end = sample.slices[0]
        self.assertAlmostEqual((end - start).total_seconds(), 20, places=3)

    def test_empty_slices_grow_to_the_populated_bucket(self) -> None:
        # Twice the limit arrives at seconds 50-59 of the first minute. The planned slices read 0-20s
        # and later empty minutes, so they hold nothing until they cover the whole populated minute.
        to = FROM + timedelta(hours=1)
        density = _SpanDensity.from_buckets([(FROM, EXACT_SPAN_LIMIT * 2)], MINUTE, FROM, to)
        sample = _plan_sample(density, FROM, to)
        assert sample is not None
        self.assertLess(sample.slices[0][1], FROM + timedelta(seconds=50))
        self.assertEqual(density.widen_to_buckets(sample, FROM).slices, [(FROM, FROM + MINUTE)])
