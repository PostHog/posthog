from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from unittest.case import skip

from posthog.constants import INSIGHT_FUNNELS, TRENDS_LINEAR, FunnelOrderType
from posthog.models.filters import Filter
from posthog.queries.funnels.funnel_time_to_convert import ClickhouseFunnelTimeToConvert

FORMAT_TIME = "%Y-%m-%d %H:%M:%S"
FORMAT_TIME_DAY_END = "%Y-%m-%d 23:59:59"


class TestFunnelTimeToConvert(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    @snapshot_clickhouse_queries
    def test_auto_bin_count_single_step(self):
        _create_person(distinct_ids=["user a"], team=self.team)
        _create_person(distinct_ids=["user b"], team=self.team)
        _create_person(distinct_ids=["user c"], team=self.team)

        _create_event(
            event="step one",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 18:00:00",
        )
        _create_event(
            event="step two",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 19:00:00",
        )
        # Converted from 0 to 1 in 3600 s
        _create_event(
            event="step three",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 21:00:00",
        )

        _create_event(
            event="step one",
            distinct_id="user b",
            team=self.team,
            timestamp="2021-06-09 13:00:00",
        )
        _create_event(
            event="step two",
            distinct_id="user b",
            team=self.team,
            timestamp="2021-06-09 13:37:00",
        )
        # Converted from 0 to 1 in 2200 s

        _create_event(
            event="step one",
            distinct_id="user c",
            team=self.team,
            timestamp="2021-06-11 07:00:00",
        )
        _create_event(
            event="step two",
            distinct_id="user c",
            team=self.team,
            timestamp="2021-06-12 06:00:00",
        )
        # Converted from 0 to 1 in 82_800 s

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

        funnel_trends = ClickhouseFunnelTimeToConvert(filter, self.team)
        results = funnel_trends.run()

        # Autobinned using the minimum time to convert, maximum time to convert, and sample count
        self.assertEqual(
            results,
            {
                "bins": [
                    (
                        2220.0,
                        2,
                    ),  # Reached step 1 from step 0 in at least 2200 s but less than 29_080 s - users A and B
                    (
                        42510.0,
                        0,
                    ),  # Analogous to above, just an interval (in this case 26_880 s) up - no users
                    (
                        82800.0,
                        1,
                    ),  # Reached step 1 from step 0 in at least 82_800 s but less than 109_680 s - user C
                ],
                "average_conversion_time": 29_540,
            },
        )

    def test_auto_bin_count_single_step_duplicate_events(self):
        # Test for CH bug that used to haunt us: https://github.com/ClickHouse/ClickHouse/issues/26580

        _create_person(distinct_ids=["user a"], team=self.team)
        _create_person(distinct_ids=["user b"], team=self.team)
        _create_person(distinct_ids=["user c"], team=self.team)

        _create_event(
            event="step one",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 18:00:00",
        )
        _create_event(
            event="step one",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 19:00:00",
        )
        # Converted from 0 to 1 in 3600 s
        _create_event(
            event="step one",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 21:00:00",
        )

        _create_event(
            event="step one",
            distinct_id="user b",
            team=self.team,
            timestamp="2021-06-09 13:00:00",
        )
        _create_event(
            event="step one",
            distinct_id="user b",
            team=self.team,
            timestamp="2021-06-09 13:37:00",
        )
        # Converted from 0 to 1 in 2200 s

        _create_event(
            event="step one",
            distinct_id="user c",
            team=self.team,
            timestamp="2021-06-11 07:00:00",
        )
        _create_event(
            event="step one",
            distinct_id="user c",
            team=self.team,
            timestamp="2021-06-12 06:00:00",
        )
        # Converted from 0 to 1 in 82_800 s

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

        funnel_trends = ClickhouseFunnelTimeToConvert(filter, self.team)
        results = funnel_trends.run()

        # Autobinned using the minimum time to convert, maximum time to convert, and sample count
        self.assertEqual(
            results,
            {
                "bins": [
                    (
                        2220.0,
                        2,
                    ),  # Reached step 1 from step 0 in at least 2200 s but less than 29_080 s - users A and B
                    (
                        42510.0,
                        0,
                    ),  # Analogous to above, just an interval (in this case 26_880 s) up - no users
                    (
                        82800.0,
                        1,
                    ),  # Reached step 1 from step 0 in at least 82_800 s but less than 109_680 s - user C
                ],
                "average_conversion_time": 29_540,
            },
        )

    def test_custom_bin_count_single_step(self):
        _create_person(distinct_ids=["user a"], team=self.team)
        _create_person(distinct_ids=["user b"], team=self.team)
        _create_person(distinct_ids=["user c"], team=self.team)

        _create_event(
            event="step one",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 18:00:00",
        )
        _create_event(
            event="step two",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 19:00:00",
        )
        # Converted from 0 to 1 in 3600 s
        _create_event(
            event="step three",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 21:00:00",
        )

        _create_event(
            event="step one",
            distinct_id="user b",
            team=self.team,
            timestamp="2021-06-09 13:00:00",
        )
        _create_event(
            event="step two",
            distinct_id="user b",
            team=self.team,
            timestamp="2021-06-09 13:37:00",
        )
        # Converted from 0 to 1 in 2200 s

        _create_event(
            event="step one",
            distinct_id="user c",
            team=self.team,
            timestamp="2021-06-11 07:00:00",
        )
        _create_event(
            event="step two",
            distinct_id="user c",
            team=self.team,
            timestamp="2021-06-12 06:00:00",
        )
        # Converted from 0 to 1 in 82_800 s

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

        funnel_trends = ClickhouseFunnelTimeToConvert(filter, self.team)
        results = funnel_trends.run()

        # 7 bins, autoscaled to work best with minimum time to convert and maximum time to convert at hand
        self.assertEqual(
            results,
            {
                "bins": [
                    (
                        2220.0,
                        2,
                    ),  # Reached step 1 from step 0 in at least 2200 s but less than 13_732 s - users A and B
                    (
                        13732.0,
                        0,
                    ),  # Analogous to above, just an interval (in this case 13_732 s) up - no users
                    (25244.0, 0),  # And so on
                    (36756.0, 0),
                    (48268.0, 0),
                    (59780.0, 0),
                    (
                        71292.0,
                        1,
                    ),  # Reached step 1 from step 0 in at least 71_292 s but less than 82_804 s - user C
                    (82804.0, 0),
                ],
                "average_conversion_time": 29_540,
            },
        )

    @skip("Compatibility issue CH 23.12 (see #21318)")
    @snapshot_clickhouse_queries
    def test_auto_bin_count_total(self):
        _create_person(distinct_ids=["user a"], team=self.team)
        _create_person(distinct_ids=["user b"], team=self.team)
        _create_person(distinct_ids=["user c"], team=self.team)

        _create_event(
            event="step one",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 18:00:00",
        )
        _create_event(
            event="step two",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 19:00:00",
        )
        _create_event(
            event="step three",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 21:00:00",
        )
        # Converted from 0 to 2 in 10_800 s

        _create_event(
            event="step one",
            distinct_id="user b",
            team=self.team,
            timestamp="2021-06-09 13:00:00",
        )
        _create_event(
            event="step two",
            distinct_id="user b",
            team=self.team,
            timestamp="2021-06-09 13:37:00",
        )

        _create_event(
            event="step one",
            distinct_id="user c",
            team=self.team,
            timestamp="2021-06-11 07:00:00",
        )
        _create_event(
            event="step two",
            distinct_id="user c",
            team=self.team,
            timestamp="2021-06-12 06:00:00",
        )

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

        funnel_trends = ClickhouseFunnelTimeToConvert(filter, self.team)
        results = funnel_trends.run()

        self.assertEqual(
            results,
            {
                "bins": [
                    (
                        10800.0,
                        1,
                    ),  # Reached step 2 from step 0 in at least 10_800 s but less than 10_860 s - user A
                    (
                        10860.0,
                        0,
                    ),  # Analogous to above, just an interval (in this case 60 s) up - no users
                ],
                "average_conversion_time": 10_800.0,
            },
        )

        # Let's verify that behavior with steps unspecified is the same as when first and last steps specified
        funnel_trends_steps_specified = ClickhouseFunnelTimeToConvert(
            Filter(data={**filter._data, "funnel_from_step": 0, "funnel_to_step": 2}),
            self.team,
        )
        results_steps_specified = funnel_trends_steps_specified.run()

        self.assertEqual(results, results_steps_specified)

    @snapshot_clickhouse_queries
    def test_basic_unordered(self):
        _create_person(distinct_ids=["user a"], team=self.team)
        _create_person(distinct_ids=["user b"], team=self.team)
        _create_person(distinct_ids=["user c"], team=self.team)

        _create_event(
            event="step three",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 18:00:00",
        )
        _create_event(
            event="step one",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 19:00:00",
        )
        _create_event(
            event="step two",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 21:00:00",
        )
        # Converted from 0 to 1 in 7200 s

        _create_event(
            event="step one",
            distinct_id="user b",
            team=self.team,
            timestamp="2021-06-09 13:00:00",
        )
        _create_event(
            event="step two",
            distinct_id="user b",
            team=self.team,
            timestamp="2021-06-09 13:37:00",
        )
        # Converted from 0 to 1 in 2200 s

        _create_event(
            event="step two",
            distinct_id="user c",
            team=self.team,
            timestamp="2021-06-11 07:00:00",
        )
        _create_event(
            event="step one",
            distinct_id="user c",
            team=self.team,
            timestamp="2021-06-12 06:00:00",
        )
        # Converted from 0 to 1 in 82_800 s

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
                "funnel_order_type": FunnelOrderType.UNORDERED,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )

        funnel_trends = ClickhouseFunnelTimeToConvert(filter, self.team)
        results = funnel_trends.run()

        # Autobinned using the minimum time to convert, maximum time to convert, and sample count
        self.assertEqual(
            results,
            {
                "bins": [
                    (
                        2220.0,
                        2,
                    ),  # Reached step 1 from step 0 in at least 2200 s but less than 29_080 s - users A and B
                    (
                        42510.0,
                        0,
                    ),  # Analogous to above, just an interval (in this case 26_880 s) up - no users
                    (
                        82800.0,
                        1,
                    ),  # Reached step 1 from step 0 in at least 82_800 s but less than 109_680 s - user C
                ],
                "average_conversion_time": 29540,
            },
        )

    @snapshot_clickhouse_queries
    def test_basic_strict(self):
        _create_person(distinct_ids=["user a"], team=self.team)
        _create_person(distinct_ids=["user b"], team=self.team)
        _create_person(distinct_ids=["user c"], team=self.team)
        _create_person(distinct_ids=["user d"], team=self.team)

        _create_event(
            event="step one",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 18:00:00",
        )
        _create_event(
            event="step two",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 19:00:00",
        )
        # Converted from 0 to 1 in 3600 s
        _create_event(
            event="step three",
            distinct_id="user a",
            team=self.team,
            timestamp="2021-06-08 21:00:00",
        )

        _create_event(
            event="step one",
            distinct_id="user b",
            team=self.team,
            timestamp="2021-06-09 13:00:00",
        )
        _create_event(
            event="step two",
            distinct_id="user b",
            team=self.team,
            timestamp="2021-06-09 13:37:00",
        )
        # Converted from 0 to 1 in 2200 s
        _create_event(
            event="blah",
            distinct_id="user b",
            team=self.team,
            timestamp="2021-06-09 13:38:00",
        )
        _create_event(
            event="step three",
            distinct_id="user b",
            team=self.team,
            timestamp="2021-06-09 13:39:00",
        )

        _create_event(
            event="step one",
            distinct_id="user c",
            team=self.team,
            timestamp="2021-06-11 07:00:00",
        )
        _create_event(
            event="step two",
            distinct_id="user c",
            team=self.team,
            timestamp="2021-06-12 06:00:00",
        )
        # Converted from 0 to 1 in 82_800 s

        _create_event(
            event="step one",
            distinct_id="user d",
            team=self.team,
            timestamp="2021-06-11 07:00:00",
        )
        _create_event(
            event="blah",
            distinct_id="user d",
            team=self.team,
            timestamp="2021-06-12 07:00:00",
        )
        # Blah cancels conversion
        _create_event(
            event="step two",
            distinct_id="user d",
            team=self.team,
            timestamp="2021-06-12 09:00:00",
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
                "funnel_order_type": FunnelOrderType.STRICT,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
            }
        )

        funnel_trends = ClickhouseFunnelTimeToConvert(filter, self.team)
        results = funnel_trends.run()

        # Autobinned using the minimum time to convert, maximum time to convert, and sample count
        self.assertEqual(
            results,
            {
                "bins": [
                    (
                        2220.0,
                        2,
                    ),  # Reached step 1 from step 0 in at least 2200 s but less than 29_080 s - users A and B
                    (
                        42510.0,
                        0,
                    ),  # Analogous to above, just an interval (in this case 26_880 s) up - no users
                    (
                        82800.0,
                        1,
                    ),  # Reached step 1 from step 0 in at least 82_800 s but less than 109_680 s - user C
                ],
                "average_conversion_time": 29540,
            },
        )
