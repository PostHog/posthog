from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from unittest.case import skip

from posthog.schema import (
    DateRange,
    EventsNode,
    FunnelConversionWindowTimeUnit,
    FunnelsFilter,
    FunnelsQuery,
    FunnelTimeToConvertResults,
    FunnelVizType,
    IntervalType,
    StepOrderValue,
)

from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner

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

        query = FunnelsQuery(
            series=[
                EventsNode(event="step one"),
                EventsNode(event="step two"),
                EventsNode(event="step three"),
            ],
            dateRange=DateRange(date_from="2021-06-07 00:00:00", date_to="2021-06-13 23:59:59"),
            interval=IntervalType.DAY,
            funnelsFilter=FunnelsFilter(
                funnelVizType=FunnelVizType.TIME_TO_CONVERT,
                funnelFromStep=0,
                funnelToStep=1,
                funnelWindowInterval=7,
                funnelWindowIntervalUnit=FunnelConversionWindowTimeUnit.DAY,
            ),
        )
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        # Autobinned using the minimum time to convert, maximum time to convert, and sample count
        self.assertEqual(
            results,
            FunnelTimeToConvertResults(
                bins=[
                    [
                        2220,
                        2,
                    ],  # Reached step 1 from step 0 in at least 2200 s but less than 29_080 s - users A and B
                    [
                        42510,
                        0,
                    ],  # Analogous to above, just an interval (in this case 26_880 s) up - no users
                    [
                        82800,
                        1,
                    ],  # Reached step 1 from step 0 in at least 82_800 s but less than 109_680 s - user C
                ],
                average_conversion_time=29_540,
            ),
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

        query = FunnelsQuery(
            series=[
                EventsNode(event="step one"),
                EventsNode(event="step one"),
                EventsNode(event="step one"),
            ],
            dateRange=DateRange(date_from="2021-06-07 00:00:00", date_to="2021-06-13 23:59:59"),
            interval=IntervalType.DAY,
            funnelsFilter=FunnelsFilter(
                funnelVizType=FunnelVizType.TIME_TO_CONVERT,
                funnelFromStep=0,
                funnelToStep=1,
                funnelWindowInterval=7,
                funnelWindowIntervalUnit=FunnelConversionWindowTimeUnit.DAY,
            ),
        )
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        # Autobinned using the minimum time to convert, maximum time to convert, and sample count
        self.assertEqual(
            results,
            FunnelTimeToConvertResults(
                bins=[
                    [
                        2220,
                        2,
                    ],  # Reached step 1 from step 0 in at least 2200 s but less than 29_080 s - users A and B
                    [
                        42510,
                        0,
                    ],  # Analogous to above, just an interval (in this case 26_880 s) up - no users
                    [
                        82800,
                        1,
                    ],  # Reached step 1 from step 0 in at least 82_800 s but less than 109_680 s - user C
                ],
                average_conversion_time=29_540,
            ),
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

        query = FunnelsQuery(
            series=[
                EventsNode(event="step one"),
                EventsNode(event="step two"),
                EventsNode(event="step three"),
            ],
            dateRange=DateRange(date_from="2021-06-07 00:00:00", date_to="2021-06-13 23:59:59"),
            interval=IntervalType.DAY,
            funnelsFilter=FunnelsFilter(
                funnelVizType=FunnelVizType.TIME_TO_CONVERT,
                funnelFromStep=0,
                funnelToStep=1,
                binCount=7,
                funnelWindowInterval=7,
                funnelWindowIntervalUnit=FunnelConversionWindowTimeUnit.DAY,
            ),
        )
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        # 7 bins, autoscaled to work best with minimum time to convert and maximum time to convert at hand
        self.assertEqual(
            results,
            FunnelTimeToConvertResults(
                bins=[
                    [
                        2220,
                        2,
                    ],  # Reached step 1 from step 0 in at least 2200 s but less than 13_732 s - users A and B
                    [
                        13732,
                        0,
                    ],  # Analogous to above, just an interval (in this case 13_732 s) up - no users
                    [25244, 0],  # And so on
                    [36756, 0],
                    [48268, 0],
                    [59780, 0],
                    [
                        71292,
                        1,
                    ],  # Reached step 1 from step 0 in at least 71_292 s but less than 82_804 s - user C
                    [82804, 0],
                ],
                average_conversion_time=29_540,
            ),
        )

    @skip("Compatibility issue CH 23.12 (see #21318)")
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

        query = FunnelsQuery(
            series=[
                EventsNode(event="step one"),
                EventsNode(event="step two"),
                EventsNode(event="step three"),
            ],
            dateRange=DateRange(date_from="2021-06-07 00:00:00", date_to="2021-06-13 23:59:59"),
            interval=IntervalType.DAY,
            funnelsFilter=FunnelsFilter(
                funnelVizType=FunnelVizType.TIME_TO_CONVERT,
                funnelWindowInterval=7,
                funnelWindowIntervalUnit=FunnelConversionWindowTimeUnit.DAY,
            ),
        )
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        self.assertEqual(
            results,
            FunnelTimeToConvertResults(
                bins=[
                    [
                        10800,
                        1,
                    ],  # Reached step 2 from step 0 in at least 10_800 s but less than 10_860 s - user A
                    [
                        10860,
                        0,
                    ],  # Analogous to above, just an interval (in this case 60 s) up - no users
                ],
                average_conversion_time=10_800,
            ),
        )

        # Let's verify that behavior with steps unspecified is the same as when first and last steps specified
        assert query.funnelsFilter is not None
        query = query.model_copy(
            update={"funnelsFilter": query.funnelsFilter.model_copy(update={"funnelFromStep": 0, "funnelToStep": 2})}
        )
        results_steps_specified = FunnelsQueryRunner(query=query, team=self.team).calculate().results

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

        query = FunnelsQuery(
            series=[
                EventsNode(event="step one"),
                EventsNode(event="step two"),
                EventsNode(event="step three"),
            ],
            dateRange=DateRange(date_from="2021-06-07 00:00:00", date_to="2021-06-13 23:59:59"),
            interval=IntervalType.DAY,
            funnelsFilter=FunnelsFilter(
                funnelVizType=FunnelVizType.TIME_TO_CONVERT,
                funnelOrderType=StepOrderValue.UNORDERED,
                funnelFromStep=0,
                funnelToStep=1,
                funnelWindowInterval=7,
                funnelWindowIntervalUnit=FunnelConversionWindowTimeUnit.DAY,
            ),
        )
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        # Autobinned using the minimum time to convert, maximum time to convert, and sample count
        self.assertEqual(
            results,
            FunnelTimeToConvertResults(
                bins=[
                    [
                        2220,
                        2,
                    ],  # Reached step 1 from step 0 in at least 2200 s but less than 29_080 s - users A and B
                    [
                        42510,
                        0,
                    ],  # Analogous to above, just an interval (in this case 26_880 s) up - no users
                    [
                        82800,
                        1,
                    ],  # Reached step 1 from step 0 in at least 82_800 s but less than 109_680 s - user C
                ],
                average_conversion_time=29540,
            ),
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

        query = FunnelsQuery(
            series=[
                EventsNode(event="step one"),
                EventsNode(event="step two"),
                EventsNode(event="step three"),
            ],
            dateRange=DateRange(date_from="2021-06-07 00:00:00", date_to="2021-06-13 23:59:59"),
            interval=IntervalType.DAY,
            funnelsFilter=FunnelsFilter(
                funnelVizType=FunnelVizType.TIME_TO_CONVERT,
                funnelOrderType=StepOrderValue.STRICT,
                funnelFromStep=0,
                funnelToStep=1,
                funnelWindowInterval=7,
                funnelWindowIntervalUnit=FunnelConversionWindowTimeUnit.DAY,
            ),
        )
        results = FunnelsQueryRunner(query=query, team=self.team).calculate().results

        # Autobinned using the minimum time to convert, maximum time to convert, and sample count
        self.assertEqual(
            results,
            FunnelTimeToConvertResults(
                bins=[
                    [
                        2220,
                        2,
                    ],  # Reached step 1 from step 0 in at least 2200 s but less than 29_080 s - users A and B
                    [
                        42510,
                        0,
                    ],  # Analogous to above, just an interval (in this case 26_880 s) up - no users
                    [
                        82800,
                        1,
                    ],  # Reached step 1 from step 0 in at least 82_800 s but less than 109_680 s - user C
                ],
                average_conversion_time=29540,
            ),
        )
