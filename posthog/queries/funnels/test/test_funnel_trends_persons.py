from datetime import datetime, timedelta
from uuid import uuid4

from django.utils import timezone

from posthog.constants import INSIGHT_FUNNELS, FunnelVizType
from posthog.models.filters import Filter
from posthog.models.session_recording_event.util import create_session_recording_event
from posthog.queries.funnels.funnel_trends_persons import ClickhouseFunnelTrendsActors
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.test.test_journeys import journeys_for


def _create_session_recording_event(team_id, distinct_id, session_id, timestamp, window_id="", has_full_snapshot=True):
    create_session_recording_event(
        uuid=uuid4(),
        team_id=team_id,
        distinct_id=distinct_id,
        timestamp=timestamp,
        session_id=session_id,
        window_id=window_id,
        snapshot_data={"timestamp": timestamp.timestamp(), "has_full_snapshot": has_full_snapshot,},
    )


filter_data = {
    "insight": INSIGHT_FUNNELS,
    "funnel_viz_type": FunnelVizType.TRENDS,
    "interval": "day",
    "date_from": "2021-05-01 00:00:00",
    "date_to": "2021-05-07 23:59:59",
    "funnel_window_days": 14,
    "funnel_from_step": 0,
    "entrance_period_start": "2021-05-01 00:00:00",
    "drop_off": False,
    "events": [{"id": "step one", "order": 0}, {"id": "step two", "order": 1}, {"id": "step three", "order": 2},],
    "include_recordings": "true",
}


class TestFunnelTrendsPersons(ClickhouseTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    def test_funnel_trend_persons_returns_recordings(self):
        persons = journeys_for(
            {
                "user_one": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1), "properties": {"$session_id": "s1a"}},
                    {"event": "step two", "timestamp": datetime(2021, 5, 2), "properties": {"$session_id": "s1b"}},
                    {"event": "step three", "timestamp": datetime(2021, 5, 3), "properties": {"$session_id": "s1c"}},
                ],
            },
            self.team,
        )
        _create_session_recording_event(self.team.pk, "user_one", "s1b", timezone.now() + timedelta(days=1))

        filter = Filter(data={"funnel_to_step": 1, **filter_data})
        _, results = ClickhouseFunnelTrendsActors(filter, self.team).get_actors()
        self.assertEqual([person["id"] for person in results], [persons["user_one"].uuid])
        self.assertEqual([person["matched_recordings"][0]["session_id"] for person in results], ["s1b"])

    @snapshot_clickhouse_queries
    def test_funnel_trend_persons_with_no_to_step(self):
        persons = journeys_for(
            {
                "user_one": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1), "properties": {"$session_id": "s1a"}},
                    {"event": "step two", "timestamp": datetime(2021, 5, 2), "properties": {"$session_id": "s1b"}},
                    {"event": "step three", "timestamp": datetime(2021, 5, 3), "properties": {"$session_id": "s1c"}},
                ],
            },
            self.team,
        )
        _create_session_recording_event(self.team.pk, "user_one", "s1c", timezone.now() + timedelta(days=1))

        filter = Filter(data=filter_data)
        _, results = ClickhouseFunnelTrendsActors(filter, self.team).get_actors()
        self.assertEqual([person["id"] for person in results], [persons["user_one"].uuid])
        self.assertEqual([person["matched_recordings"][0]["session_id"] for person in results], ["s1c"])

    @snapshot_clickhouse_queries
    def test_funnel_trend_persons_with_drop_off(self):
        persons = journeys_for(
            {
                "user_one": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1), "properties": {"$session_id": "s1a"}},
                ],
            },
            self.team,
        )
        _create_session_recording_event(self.team.pk, "user_one", "s1a", timezone.now() + timedelta(days=1))

        filter = Filter(data={**filter_data, "drop_off": True})
        _, results = ClickhouseFunnelTrendsActors(filter, self.team).get_actors()
        self.assertEqual([person["id"] for person in results], [persons["user_one"].uuid])
        self.assertEqual([person["matched_recordings"][0].get("session_id") for person in results], ["s1a"])
