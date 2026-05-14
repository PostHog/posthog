from datetime import datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from posthog.schema import (
    BreakdownFilter,
    DateRange,
    EventsNode,
    FunnelsFilter,
    FunnelsQuery,
    FunnelVizType,
    IntervalType,
)

from posthog.hogql_queries.insights.funnels.test.test_funnel_persons import get_actors
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.test_journeys import journeys_for

funnels_query = FunnelsQuery(
    series=[
        EventsNode(event="step one"),
        EventsNode(event="step two"),
        EventsNode(event="step three"),
    ],
    interval=IntervalType.DAY,
    dateRange=DateRange(date_from="2021-05-01 00:00:00", date_to="2021-05-07 23:59:59"),
    funnelsFilter=FunnelsFilter(
        funnelVizType=FunnelVizType.TRENDS,
        funnelFromStep=0,
    ),
)


@freeze_time("2021-05-01")
class TestFunnelTrendsActors(ClickhouseTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    def test_funnel_trend_persons_returns_recordings(self):
        persons = journeys_for(
            {
                "user_one": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1),
                        "properties": {"$session_id": "s1a"},
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 2),
                        "properties": {"$session_id": "s1b"},
                    },
                    {
                        "event": "step three",
                        "timestamp": datetime(2021, 5, 3),
                        "properties": {"$session_id": "s1c"},
                    },
                ]
            },
            self.team,
        )
        timestamp = datetime(2021, 5, 1)
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s1b",
            distinct_id="user_one",
            first_timestamp=timestamp,
            last_timestamp=timestamp,
        )

        assert funnels_query.funnelsFilter
        results = get_actors(
            funnels_query.model_copy(
                update={"funnelsFilter": funnels_query.funnelsFilter.model_copy(update={"funnelToStep": 1})}
            ),
            self.team,
            funnel_trends_drop_off=False,
            funnel_trends_entrance_period_start="2021-05-01 00:00:00",
            include_recordings=True,
        )

        # self.assertEqual([person[0]["id"] for person in results], [persons["user_one"].uuid])
        self.assertEqual(results[0][0], persons["user_one"].uuid)
        self.assertEqual(
            # [person["matched_recordings"][0]["session_id"] for person in results],
            [next(iter(results[0][2]))["session_id"]],
            ["s1b"],
        )

    @snapshot_clickhouse_queries
    def test_funnel_trend_persons_with_no_to_step(self):
        persons = journeys_for(
            {
                "user_one": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1),
                        "properties": {"$session_id": "s1a"},
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 2),
                        "properties": {"$session_id": "s1b"},
                    },
                    {
                        "event": "step three",
                        "timestamp": datetime(2021, 5, 3),
                        "properties": {"$session_id": "s1c"},
                    },
                ]
            },
            self.team,
        )
        # the session recording can start a little before the events in the funnel
        timestamp = datetime(2021, 5, 1) - timedelta(hours=12)
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s1c",
            distinct_id="user_one",
            first_timestamp=timestamp,
            last_timestamp=timestamp,
        )

        results = get_actors(
            funnels_query,
            self.team,
            funnel_trends_drop_off=False,
            funnel_trends_entrance_period_start="2021-05-01 00:00:00",
            include_recordings=True,
        )

        # self.assertEqual([person[0]["id"] for person in results], [persons["user_one"].uuid])
        self.assertEqual(results[0][0], persons["user_one"].uuid)
        self.assertEqual(
            # [person["matched_recordings"][0]["session_id"] for person in results],
            [next(iter(results[0][2]))["session_id"]],
            ["s1c"],
        )

    @snapshot_clickhouse_queries
    def test_funnel_trend_persons_filters_by_breakdown(self):
        persons = journeys_for(
            {
                "chrome_user": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 1, 1),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "step three",
                        "timestamp": datetime(2021, 5, 1, 2),
                        "properties": {"$browser": "Chrome"},
                    },
                ],
                "safari_user": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1),
                        "properties": {"$browser": "Safari"},
                    },
                    {
                        "event": "step two",
                        "timestamp": datetime(2021, 5, 1, 1),
                        "properties": {"$browser": "Safari"},
                    },
                    {
                        "event": "step three",
                        "timestamp": datetime(2021, 5, 1, 2),
                        "properties": {"$browser": "Safari"},
                    },
                ],
            },
            self.team,
        )

        breakdown_query = funnels_query.model_copy(
            update={"breakdownFilter": BreakdownFilter(breakdown="$browser", breakdown_type="event")}
        )

        chrome_results = get_actors(
            breakdown_query,
            self.team,
            funnel_trends_drop_off=False,
            funnel_trends_entrance_period_start="2021-05-01 00:00:00",
            funnel_step_breakdown=["Chrome"],
        )
        assert [row[0] for row in chrome_results] == [persons["chrome_user"].uuid]

        safari_results = get_actors(
            breakdown_query,
            self.team,
            funnel_trends_drop_off=False,
            funnel_trends_entrance_period_start="2021-05-01 00:00:00",
            funnel_step_breakdown=["Safari"],
        )
        assert [row[0] for row in safari_results] == [persons["safari_user"].uuid]

        all_results = get_actors(
            breakdown_query,
            self.team,
            funnel_trends_drop_off=False,
            funnel_trends_entrance_period_start="2021-05-01 00:00:00",
        )
        assert sorted(row[0] for row in all_results) == sorted(
            [persons["chrome_user"].uuid, persons["safari_user"].uuid]
        )

    @snapshot_clickhouse_queries
    def test_funnel_trend_persons_with_drop_off(self):
        persons = journeys_for(
            {
                "user_one": [
                    {
                        "event": "step one",
                        "timestamp": datetime(2021, 5, 1),
                        "properties": {"$session_id": "s1a"},
                    }
                ]
            },
            self.team,
        )
        timestamp = datetime(2021, 5, 1)
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s1a",
            distinct_id="user_one",
            first_timestamp=timestamp,
            last_timestamp=timestamp,
        )

        results = get_actors(
            funnels_query,
            self.team,
            funnel_trends_drop_off=True,
            funnel_trends_entrance_period_start="2021-05-01 00:00:00",
            include_recordings=True,
        )

        # self.assertEqual([person[0]["id"] for person in results], [persons["user_one"].uuid])
        self.assertEqual(results[0][0], persons["user_one"].uuid)
        self.assertEqual(
            # [person["matched_recordings"][0].get("session_id") for person in results],
            [next(iter(results[0][2]))["session_id"]],
            ["s1a"],
        )
