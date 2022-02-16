from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from freezegun import freeze_time

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.session_recording_event import create_session_recording_event
from ee.clickhouse.queries.funnels.funnel_trends_persons import ClickhouseFunnelTrendsActors
from ee.clickhouse.queries.funnels.funnel_unordered_persons import ClickhouseFunnelUnorderedActors
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.constants import FUNNEL_VIZ_TYPE, INSIGHT_FUNNELS, FunnelVizType
from posthog.models.filters import Filter
from posthog.models.person import Person
from posthog.test.base import APIBaseTest, test_with_materialized_columns

FORMAT_TIME = "%Y-%m-%d 00:00:00"


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
                "user_two": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1), "properties": {"$session_id": "s2a"}},
                    {"event": "step two", "timestamp": datetime(2021, 5, 2), "properties": {"$session_id": "s2b"}},
                ],
                "user_three": [
                    {"event": "step one", "timestamp": datetime(2021, 5, 1), "properties": {"$session_id": "s3a"}},
                ],
            },
            self.team,
        )
        _create_session_recording_event(self.team.pk, "user_one", "s1b", timezone.now() + timedelta(days=1))
        _create_session_recording_event(self.team.pk, "user_one", "s1c", timezone.now() + timedelta(days=1))
        _create_session_recording_event(self.team.pk, "user_two", "s2b", timezone.now() + timedelta(days=1))
        _create_session_recording_event(self.team.pk, "user_three", "s3a", timezone.now() + timedelta(days=1))

        filter_data = {
            "insight": INSIGHT_FUNNELS,
            "funnel_viz_type": FunnelVizType.TRENDS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 23:59:59",
            "funnel_window_days": 14,
            "funnel_from_step": 0,
            "funnel_to_step": 1,
            "entrance_period_start": "2021-05-01 00:00:00",
            "drop_off": False,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
            "include_recordings": "true",
        }

        filter = Filter(data=filter_data)
        _, results = ClickhouseFunnelTrendsActors(filter, self.team).get_actors()
        self.assertEqual([person["id"] for person in results], [persons["user_one"].uuid, persons["user_two"].uuid])
        self.assertEqual([person["matched_recordings"][0]["session_id"] for person in results], ["s1b", "s2b"])

        filter_data.update({"funnel_to_step": None})
        filter = Filter(data=filter_data)
        _, results = ClickhouseFunnelTrendsActors(filter, self.team).get_actors()
        self.assertEqual([person["id"] for person in results], [persons["user_one"].uuid])
        self.assertEqual([person["matched_recordings"][0]["session_id"] for person in results], ["s1c"])

        filter_data.update({"drop_off": True})
        filter = Filter(data=filter_data)
        _, results = ClickhouseFunnelTrendsActors(filter, self.team).get_actors()
        self.assertEqual([person["id"] for person in results], [persons["user_two"].uuid, persons["user_three"].uuid])
        self.assertEqual([person["matched_recordings"][0].get("session_id") for person in results], ["s2b", "s3a"])
