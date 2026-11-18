from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.apm.backend.logic.health.dependencies import EXACT_SPAN_LIMIT, MAX_SAMPLE_SLICES, _plan_sample

FROM = datetime(2026, 6, 2, 8, 0, tzinfo=UTC)


class TestPlanSample(SimpleTestCase):
    def test_window_under_the_limit_is_read_whole(self) -> None:
        self.assertIsNone(_plan_sample(EXACT_SPAN_LIMIT, FROM, FROM + timedelta(hours=1)))

    @parameterized.expand(
        [
            ("hour_at_ten_times_the_limit", timedelta(hours=1), 10, 6),
            ("day_at_a_thousand_times_the_limit", timedelta(days=1), 1000, 1),
            ("day_just_over_the_limit", timedelta(days=1), 1.25, MAX_SAMPLE_SLICES),
        ]
    )
    def test_slices_read_the_limit_share_of_the_window(
        self, _name: str, window: timedelta, overload: float, slices: int
    ) -> None:
        to = FROM + window
        sample = _plan_sample(int(EXACT_SPAN_LIMIT * overload), FROM, to)
        assert sample is not None
        self.assertEqual(len(sample.slices), slices)
        self.assertAlmostEqual(sample.rate, 1 / overload, places=6)
        read = sum(((end - start) for start, end in sample.slices), timedelta(0))
        self.assertAlmostEqual(read / window, sample.rate, places=6)
        self.assertTrue(all(FROM <= start < end <= to for start, end in sample.slices))
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(sample.slices, sample.slices[1:])))
