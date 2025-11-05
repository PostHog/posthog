from datetime import datetime, timedelta
from uuid import UUID

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)

from django.utils import timezone

from posthog.constants import INSIGHT_FUNNELS
from posthog.hogql_queries.insights.funnels.test.test_funnel_persons import get_actors
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.test_journeys import journeys_for

FORMAT_TIME = "%Y-%m-%d 00:00:00"


class BaseTestFunnelStrictStepsPersons(ClickhouseTestMixin, APIBaseTest):
    __test__ = False

    def _create_sample_data_multiple_dropoffs(self):
        events_by_person = {}
        for i in range(5):
            events_by_person[f"user_{i}"] = [
                {"event": "step one", "timestamp": datetime(2021, 5, 1)},
                {"event": "step fake", "timestamp": datetime(2021, 5, 2)},
                {"event": "step two", "timestamp": datetime(2021, 5, 3)},
                {"event": "step three", "timestamp": datetime(2021, 5, 5)},
            ]

        for i in range(5, 15):
            events_by_person[f"user_{i}"] = [
                {"event": "step one", "timestamp": datetime(2021, 5, 1)},
                {"event": "step two", "timestamp": datetime(2021, 5, 3)},
            ]

        for i in range(15, 35):
            events_by_person[f"user_{i}"] = [{"event": "step one", "timestamp": datetime(2021, 5, 1)}]

        journeys_for(events_by_person, self.team)

    def test_first_step(self):
        self._create_sample_data_multiple_dropoffs()
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        results = get_actors(filters, self.team, funnel_step=1)

        self.assertEqual(35, len(results))

    def test_second_step(self):
        self._create_sample_data_multiple_dropoffs()
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        results = get_actors(filters, self.team, funnel_step=2)

        self.assertEqual(10, len(results))

    def test_second_step_dropoff(self):
        self._create_sample_data_multiple_dropoffs()
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        results = get_actors(filters, self.team, funnel_step=-2)

        self.assertEqual(25, len(results))

    def test_third_step(self):
        self._create_sample_data_multiple_dropoffs()
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
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

        results = get_actors(filters, self.team, funnel_step=3)

        self.assertEqual(0, len(results))

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-02 00:00:00.000Z")
    def test_strict_funnel_person_recordings(self):
        p1 = _create_person(distinct_ids=[f"user_1"], team=self.team)
        _create_event(
            event="step one",
            distinct_id="user_1",
            team=self.team,
            timestamp=timezone.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            properties={"$session_id": "s1", "$window_id": "w1"},
            event_uuid="11111111-1111-1111-1111-111111111111",
        )
        _create_event(
            event="step two",
            distinct_id="user_1",
            team=self.team,
            timestamp=(timezone.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S.%f"),
            properties={"$session_id": "s2", "$window_id": "w2"},
            event_uuid="21111111-1111-1111-1111-111111111111",
        )
        _create_event(
            event="interupting step",
            distinct_id="user_1",
            team=self.team,
            timestamp=(timezone.now() + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S.%f"),
            properties={"$session_id": "s2", "$window_id": "w2"},
            event_uuid="21111111-1111-1111-1111-111111111111",
        )
        _create_event(
            event="step three",
            distinct_id="user_1",
            team=self.team,
            timestamp=(timezone.now() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S.%f"),
            properties={"$session_id": "s2", "$window_id": "w2"},
            event_uuid="21111111-1111-1111-1111-111111111111",
        )
        timestamp = datetime(2021, 1, 3, 0, 0, 0)
        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s2",
            distinct_id="user_1",
            first_timestamp=timestamp,
            last_timestamp=timestamp,
            ensure_analytics_event_in_session=False,  # Would mess up the strict funnel
        )

        # First event, but no recording
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
            "date_from": "2021-01-01",
            "date_to": "2021-01-08",
            "interval": "day",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        results = get_actors(filters, self.team, funnel_step=1, include_recordings=True)

        # self.assertEqual(results[0]["id"], p1.uuid)
        self.assertEqual(results[0][0], p1.uuid)
        self.assertEqual(
            # results[0]["matched_recordings"],
            list(results[0][2]),
            [],
        )

        # Second event, with recording
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
            "date_from": "2021-01-01",
            "date_to": "2021-01-08",
            "interval": "day",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        results = get_actors(filters, self.team, funnel_step=2, include_recordings=True)

        # self.assertEqual(results[0]["id"], p1.uuid)
        self.assertEqual(results[0][0], p1.uuid)
        self.assertEqual(
            # results[0]["matched_recordings"],
            list(results[0][2]),
            [
                {
                    "session_id": "s2",
                    "events": [
                        {
                            "uuid": UUID("21111111-1111-1111-1111-111111111111"),
                            "timestamp": timezone.now() + timedelta(days=1),
                            "window_id": "w2",
                        }
                    ],
                }
            ],
        )

        # Third event dropoff, with recording
        filters = {
            "insight": INSIGHT_FUNNELS,
            "funnel_order_type": "strict",
            "date_from": "2021-01-01",
            "date_to": "2021-01-08",
            "interval": "day",
            "funnel_window_days": 7,
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        results = get_actors(filters, self.team, funnel_step=-3, include_recordings=True)

        # self.assertEqual(results[0]["id"], p1.uuid)
        self.assertEqual(results[0][0], p1.uuid)
        self.assertEqual(
            # results[0]["matched_recordings"],
            list(results[0][2]),
            [
                {
                    "session_id": "s2",
                    "events": [
                        {
                            "uuid": UUID("21111111-1111-1111-1111-111111111111"),
                            "timestamp": timezone.now() + timedelta(days=1),
                            "window_id": "w2",
                        }
                    ],
                }
            ],
        )


class TestFunnelStrictStepsPersons(BaseTestFunnelStrictStepsPersons):
    __test__ = True
