from datetime import datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from posthog.constants import INSIGHT_FUNNELS, FunnelVizType
from posthog.hogql_queries.insights.funnels.test.test_funnel_persons import get_actors
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.test_journeys import journeys_for

filters = {
    "insight": INSIGHT_FUNNELS,
    "funnel_viz_type": FunnelVizType.TRENDS,
    "interval": "day",
    "date_from": "2021-05-01 00:00:00",
    "date_to": "2021-05-07 23:59:59",
    "funnel_window_days": 14,
    "funnel_from_step": 0,
    "events": [
        {"id": "step one", "order": 0},
        {"id": "step two", "order": 1},
        {"id": "step three", "order": 2},
    ],
}


@freeze_time("2021-05-01")
class BaseTestFunnelTrendsActors(ClickhouseTestMixin, APIBaseTest):
    __test__ = False

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

        results = get_actors(
            {"funnel_to_step": 1, **filters},
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
            filters,
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
            filters,
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


class TestFunnelTrendsActors(BaseTestFunnelTrendsActors):
    __test__ = True
