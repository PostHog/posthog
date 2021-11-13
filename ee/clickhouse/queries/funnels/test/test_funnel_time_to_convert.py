import unittest
from datetime import datetime

from ee.clickhouse.queries.funnels import ClickhouseFunnel, ClickhouseFunnelStrict, ClickhouseFunnelUnordered
from ee.clickhouse.queries.funnels.funnel_time_to_convert import ClickhouseFunnelTimeToConvert
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS, TRENDS_LINEAR
from posthog.models.filters import Filter
from posthog.test.base import APIBaseTest

FORMAT_TIME = "%Y-%m-%d %H:%M:%S"
FORMAT_TIME_DAY_END = "%Y-%m-%d 23:59:59"


class TestFunnelTrends(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def setup_trends_journey(self):
        journeys_for(
            {
                "user a": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 8, 18)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 8, 19)},
                    # Converted from 0 to 1 in 3600 s
                    {"event": "step three", "timestamp": datetime(2021, 6, 8, 21)},
                ],
                "user b": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 9, 13)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 9, 13, 37)},
                    # Converted from 0 to 1 in 2200 s
                ],
                "user c": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 11, 7)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 12, 6)},
                    # Converted from 0 to 1 in 82_800 s
                ],
            },
            self.team,
        )

    def test_auto_bin_count_single_step(self):
        self.setup_trends_journey()

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "interval": "day",
                "date_from": "2021-06-07 00:00:00",
                "date_to": "2021-06-13 23:59:59",
                "funnel_from_step": 0,
                "funnel_to_step": 1,
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )

        funnel_trends = ClickhouseFunnelTimeToConvert(filter, self.team, ClickhouseFunnel)
        results = funnel_trends.run()

        # Autobinned using the minimum time to convert, maximum time to convert, and sample count
        self.assertEqual(
            results,
            {
                "bins": [
                    (2220.0, 2),  # Reached step 1 from step 0 in at least 2200 s but less than 29_080 s - users A and B
                    (29080.0, 0),  # Analogous to above, just an interval (in this case 26_880 s) up - no users
                    (55940.0, 0),  # Same as above
                    (82800.0, 1),  # Reached step 1 from step 0 in at least 82_800 s but less than 109_680 s - user C
                ],
                "average_conversion_time": 29_540,
            },
        )

    @unittest.skip("Wait for bug to be resolved")
    def test_auto_bin_count_single_step_duplicate_events(self):
        # demonstrates existing CH bug. Current patch is to remove negative times from consideration
        # Reference on what happens: https://github.com/ClickHouse/ClickHouse/issues/26580

        journeys_for(
            {
                "user a": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 8, 18)},
                    {"event": "step one", "timestamp": datetime(2021, 6, 8, 19)},
                    # Converted from 0 to 1 in 3600 s
                    {"event": "step one", "timestamp": datetime(2021, 6, 8, 21)},
                ],
                "user b": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 9, 13)},
                    {"event": "step one", "timestamp": datetime(2021, 6, 9, 13, 37)},
                    # Converted from 0 to 1 in 2200 s
                ],
                "user c": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 11, 7)},
                    {"event": "step one", "timestamp": datetime(2021, 6, 12, 6)},
                    # Converted from 0 to 1 in 82_800 s
                ],
            },
            self.team,
        )

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "interval": "day",
                "date_from": "2021-06-07 00:00:00",
                "date_to": "2021-06-13 23:59:59",
                "funnel_from_step": 0,
                "funnel_to_step": 1,
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step one", "order": 1},
                    {"id": "step one", "order": 2},
                ],
            }
        )

        funnel_trends = ClickhouseFunnelTimeToConvert(filter, self.team, ClickhouseFunnel)
        results = funnel_trends.run()

        # Autobinned using the minimum time to convert, maximum time to convert, and sample count
        self.assertEqual(
            results,
            {
                "bins": [
                    (2220.0, 2),  # Reached step 1 from step 0 in at least 2200 s but less than 29_080 s - users A and B
                    (29080.0, 0),  # Analogous to above, just an interval (in this case 26_880 s) up - no users
                    (55940.0, 0),  # Same as above
                    (82800.0, 1),  # Reached step 1 from step 0 in at least 82_800 s but less than 109_680 s - user C
                ],
                "average_conversion_time": 29_540,
            },
        )

    def test_custom_bin_count_single_step(self):
        self.setup_trends_journey()

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "interval": "day",
                "date_from": "2021-06-07 00:00:00",
                "date_to": "2021-06-13 23:59:59",
                "funnel_from_step": 0,
                "funnel_to_step": 1,
                "funnel_window_days": 7,
                "bin_count": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )

        funnel_trends = ClickhouseFunnelTimeToConvert(filter, self.team, ClickhouseFunnel)
        results = funnel_trends.run()

        # 7 bins, autoscaled to work best with minimum time to convert and maximum time to convert at hand
        self.assertEqual(
            results,
            {
                "bins": [
                    (2220.0, 2),  # Reached step 1 from step 0 in at least 2200 s but less than 13_732 s - users A and B
                    (13732.0, 0),  # Analogous to above, just an interval (in this case 13_732 s) up - no users
                    (25244.0, 0),  # And so on
                    (36756.0, 0),
                    (48268.0, 0),
                    (59780.0, 0),
                    (71292.0, 1),  # Reached step 1 from step 0 in at least 71_292 s but less than 82_804 s - user C
                    (82804.0, 0),
                ],
                "average_conversion_time": 29_540,
            },
        )

    def test_auto_bin_count_total(self):
        self.setup_trends_journey()

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "interval": "day",
                "date_from": "2021-06-07 00:00:00",
                "date_to": "2021-06-13 23:59:59",
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )

        funnel_trends = ClickhouseFunnelTimeToConvert(filter, self.team, ClickhouseFunnel)
        results = funnel_trends.run()

        self.assertEqual(
            results,
            {
                "bins": [
                    (10800.0, 1),  # Reached step 2 from step 0 in at least 10_800 s but less than 10_860 s - user A
                    (10860.0, 0),  # Analogous to above, just an interval (in this case 60 s) up - no users
                    (10920.0, 0),  # And so on
                    (10980.0, 0),
                ],
                "average_conversion_time": 10_800,
            },
        )

        # Let's verify that behavior with steps unspecified is the same as when first and last steps specified
        funnel_trends_steps_specified = ClickhouseFunnelTimeToConvert(
            Filter(data={**filter._data, "funnel_from_step": 0, "funnel_to_step": 2}), self.team, ClickhouseFunnel
        )
        results_steps_specified = funnel_trends_steps_specified.run()

        self.assertEqual(results, results_steps_specified)

    def test_basic_unordered(self):
        journeys_for(
            {
                "user a": [
                    {"event": "step three", "timestamp": datetime(2021, 6, 8, 18)},
                    {"event": "step one", "timestamp": datetime(2021, 6, 8, 19)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 8, 21)},
                    # Converted from 0 to 1 in 7200 s
                ],
                "user b": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 9, 13)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 9, 13, 37)},
                    # Converted from 0 to 1 in 2200 s
                ],
                "user c": [
                    {"event": "step two", "timestamp": datetime(2021, 6, 11, 7)},
                    {"event": "step one", "timestamp": datetime(2021, 6, 12, 6)},
                    # Converted from 0 to 1 in 82_800 s
                ],
            },
            self.team,
        )

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-06-07 00:00:00",
                "date_to": "2021-06-13 23:59:59",
                "funnel_from_step": 0,
                "funnel_to_step": 1,
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )

        funnel_trends = ClickhouseFunnelTimeToConvert(filter, self.team, ClickhouseFunnelUnordered)
        results = funnel_trends.run()

        # Autobinned using the minimum time to convert, maximum time to convert, and sample count
        self.assertEqual(
            results,
            {
                "bins": [
                    (2220.0, 2),  # Reached step 1 from step 0 in at least 2200 s but less than 29_080 s - users A and B
                    (29080.0, 0),  # Analogous to above, just an interval (in this case 26_880 s) up - no users
                    (55940.0, 0),  # Same as above
                    (82800.0, 1),  # Reached step 1 from step 0 in at least 82_800 s but less than 109_680 s - user C
                ],
                "average_conversion_time": 29540,
            },
        )

    def test_basic_strict(self):
        journeys_for(
            {
                "user a": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 8, 18)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 8, 19)},
                    # Converted from 0 to 1 in 3600 s
                    {"event": "step three", "timestamp": datetime(2021, 6, 8, 21)},
                ],
                "user b": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 9, 13)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 9, 13, 37)},
                    # Converted from 0 to 1 in 2200 s
                    {"event": "blah", "timestamp": datetime(2021, 6, 9, 13, 38)},
                    {"event": "step three", "timestamp": datetime(2021, 6, 9, 13, 39)},
                ],
                "user c": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 11, 7)},
                    {"event": "step two", "timestamp": datetime(2021, 6, 12, 6)},
                    # Converted from 0 to 1 in 82_800 s
                ],
                "user d": [
                    {"event": "step one", "timestamp": datetime(2021, 6, 11, 7)},
                    {"event": "blah", "timestamp": datetime(2021, 6, 9, 12, 7)},
                    # Blah cancels conversion
                    {"event": "step two", "timestamp": datetime(2021, 6, 12, 9)},
                ],
            },
            self.team,
        )

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "display": TRENDS_LINEAR,
                "interval": "day",
                "date_from": "2021-06-07 00:00:00",
                "date_to": "2021-06-13 23:59:59",
                "funnel_from_step": 0,
                "funnel_to_step": 1,
                "funnel_window_days": 7,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )

        funnel_trends = ClickhouseFunnelTimeToConvert(filter, self.team, ClickhouseFunnelStrict)
        results = funnel_trends.run()

        # Autobinned using the minimum time to convert, maximum time to convert, and sample count
        self.assertEqual(
            results,
            {
                "bins": [
                    (2220.0, 2),  # Reached step 1 from step 0 in at least 2200 s but less than 29_080 s - users A and B
                    (29080.0, 0),  # Analogous to above, just an interval (in this case 26_880 s) up - no users
                    (55940.0, 0),  # Same as above
                    (82800.0, 1),  # Reached step 1 from step 0 in at least 82_800 s but less than 109_680 s - user C
                ],
                "average_conversion_time": 29540,
            },
        )
