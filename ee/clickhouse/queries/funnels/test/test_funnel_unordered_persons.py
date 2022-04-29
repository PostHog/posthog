from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from freezegun import freeze_time

from ee.clickhouse.models.session_recording_event import create_session_recording_event
from ee.clickhouse.queries.funnels.funnel_unordered_persons import ClickhouseFunnelUnorderedActors
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.constants import INSIGHT_FUNNELS
from posthog.models.filters import Filter
from posthog.test.base import APIBaseTest, _create_event, _create_person

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


class TestFunnelUnorderedStepsPersons(ClickhouseTestMixin, APIBaseTest):
    def _create_sample_data_multiple_dropoffs(self):
        events_by_person = {}
        for i in range(5):
            events_by_person[f"user_{i}"] = [
                {"event": "step one", "timestamp": datetime(2021, 5, 1)},
                {"event": "step three", "timestamp": datetime(2021, 5, 3)},
                {"event": "step two", "timestamp": datetime(2021, 5, 5)},
            ]

        for i in range(5, 15):
            events_by_person[f"user_{i}"] = [
                {"event": "step two", "timestamp": datetime(2021, 5, 1)},
                {"event": "step one", "timestamp": datetime(2021, 5, 3)},
            ]

        for i in range(15, 35):
            events_by_person[f"user_{i}"] = [{"event": "step one", "timestamp": datetime(2021, 5, 1)}]

        journeys_for(events_by_person, self.team)

    def test_invalid_steps(self):
        data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "funnel_step": "blah",
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        filter = Filter(data=data)
        with self.assertRaises(ValueError):
            ClickhouseFunnelUnorderedActors(filter, self.team).run()

        filter = filter.with_data({"funnel_step": -1})
        with pytest.raises(ValueError):
            _, _ = ClickhouseFunnelUnorderedActors(filter, self.team).run()

    def test_first_step(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "funnel_step": 1,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        filter = Filter(data=data)
        _, serialized_results = ClickhouseFunnelUnorderedActors(filter, self.team).get_actors()
        self.assertEqual(35, len(serialized_results))

    def test_last_step(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "funnel_step": 3,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        filter = Filter(data=data)
        _, serialized_results = ClickhouseFunnelUnorderedActors(filter, self.team).get_actors()
        self.assertEqual(5, len(serialized_results))

    def test_second_step_dropoff(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "funnel_step": -2,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        filter = Filter(data=data)
        _, serialized_results = ClickhouseFunnelUnorderedActors(filter, self.team).get_actors()
        self.assertEqual(20, len(serialized_results))

    def test_last_step_dropoff(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "funnel_step": -3,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }
        filter = Filter(data=data)
        _, serialized_results = ClickhouseFunnelUnorderedActors(filter, self.team).get_actors()
        self.assertEqual(10, len(serialized_results))

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-02 00:00:00.000Z")
    def test_unordered_funnel_does_not_return_recordings(self):
        p1 = _create_person(distinct_ids=[f"user_1"], team=self.team)
        _create_event(
            event="step two",
            distinct_id="user_1",
            team=self.team,
            timestamp=timezone.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            properties={"$session_id": "s1", "$window_id": "w1"},
            event_uuid="21111111-1111-1111-1111-111111111111",
        )
        _create_event(
            event="step one",
            distinct_id="user_1",
            team=self.team,
            timestamp=(timezone.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S.%f"),
            properties={"$session_id": "s1", "$window_id": "w1"},
            event_uuid="11111111-1111-1111-1111-111111111111",
        )

        _create_session_recording_event(self.team.pk, "user_1", "s1", timezone.now() + timedelta(days=1))

        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "date_from": "2021-01-01",
                "date_to": "2021-01-08",
                "interval": "day",
                "funnel_window_days": 7,
                "funnel_step": 1,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
                "include_recordings": "true",  # <- The important line
            }
        )
        _, results = ClickhouseFunnelUnorderedActors(filter, self.team).get_actors()
        self.assertEqual(results[0]["id"], p1.uuid)
        self.assertEqual(
            results[0]["matched_recordings"], [],
        )
