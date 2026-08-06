from django.test import SimpleTestCase

from posthog.hogql_queries.insights.funnels.funnel_time_to_convert_bins import (
    ConversionTimeRange,
    compute_shared_bin_boundaries,
)


class TestSharedBinComputer(SimpleTestCase):
    def test_spans_union_of_both_period_ranges(self):
        current = ConversionTimeRange(min_timing=100, max_timing=200, sample_count=8)
        previous = ConversionTimeRange(min_timing=50, max_timing=300, sample_count=19)

        boundaries = compute_shared_bin_boundaries(current, previous)

        # Union range [50, 300], 27 samples -> ceil(cbrt(27)) = 3 bins, width ceil(250/3) = 84.
        self.assertEqual(boundaries, [50, 134, 218, 302])

    def test_falls_back_to_the_only_populated_period(self):
        # Previous period has no conversions; boundaries come from the current period alone.
        current = ConversionTimeRange(min_timing=100, max_timing=200, sample_count=8)
        previous = ConversionTimeRange(min_timing=0, max_timing=0, sample_count=0)

        boundaries = compute_shared_bin_boundaries(current, previous)

        # 8 samples -> ceil(cbrt(8)) = 2 bins over [100, 200], width ceil(100/2) = 50.
        self.assertEqual(boundaries, [100, 150, 200])

    def test_treats_missing_period_like_empty_period(self):
        current = ConversionTimeRange(min_timing=100, max_timing=200, sample_count=8)

        self.assertEqual(
            compute_shared_bin_boundaries(current, None),
            compute_shared_bin_boundaries(current, ConversionTimeRange(0, 0, 0)),
        )

    def test_returns_no_boundaries_when_neither_period_converted(self):
        self.assertEqual(compute_shared_bin_boundaries(None, None), [])
        self.assertEqual(
            compute_shared_bin_boundaries(ConversionTimeRange(0, 0, 0), ConversionTimeRange(0, 0, 0)),
            [],
        )

    def test_bin_count_override_replaces_the_auto_count(self):
        current = ConversionTimeRange(min_timing=0, max_timing=100, sample_count=8)
        previous = ConversionTimeRange(min_timing=0, max_timing=100, sample_count=8)

        boundaries = compute_shared_bin_boundaries(current, previous, bin_count_override=4)

        # 4 bins over [0, 100], width ceil(100/4) = 25 -> 5 boundaries.
        self.assertEqual(boundaries, [0, 25, 50, 75, 100])
        self.assertEqual(len(boundaries), 5)
