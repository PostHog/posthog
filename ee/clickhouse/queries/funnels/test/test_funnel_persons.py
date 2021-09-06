from datetime import datetime
from uuid import uuid4

from freezegun.api import freeze_time

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.session_recording_event import create_session_recording_event
from ee.clickhouse.queries.funnels.funnel_persons import ClickhouseFunnelPersons
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.constants import INSIGHT_FUNNELS
from posthog.models import Cohort, Filter
from posthog.models.person import Person
from posthog.test.base import APIBaseTest, test_with_materialized_columns

FORMAT_TIME = "%Y-%m-%d 00:00:00"
MAX_STEP_COLUMN = 0
COUNT_COLUMN = 1
PERSON_ID_COLUMN = 2


def _create_person(**kwargs):
    return Person.objects.create(**kwargs)


def _create_event(**kwargs):
    create_event(event_uuid=uuid4(), **kwargs)


def _create_session_recording_event(**kwargs):
    create_session_recording_event(
        uuid=uuid4(), **kwargs,
    )


class TestFunnelPersons(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_session_recording_snapshot(self, distinct_id, session_id, timestamp, type=2):
        _create_session_recording_event(
            team_id=self.team.pk,
            distinct_id=distinct_id,
            timestamp=timestamp,
            session_id=session_id,
            snapshot_data={"timestamp": timestamp.timestamp(), "type": type},
        )

    def _create_sample_data(self):
        for i in range(110):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-03 00:00:00")
            _create_event(event="step three", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-05 00:00:00")

    def _create_sample_data_multiple_dropoffs(self):
        for i in range(5):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-03 00:00:00")
            _create_event(event="step three", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-05 00:00:00")

        for i in range(5, 15):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-03 00:00:00")

        for i in range(15, 35):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")

    def _create_browser_breakdown_events(self):
        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk, properties={"$country": "PL"})
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person1",
            properties={"key": "val", "$browser": "Chrome"},
            timestamp="2020-01-01T12:00:00Z",
        )
        _create_event(
            team=self.team,
            event="play movie",
            distinct_id="person1",
            properties={"key": "val", "$browser": "Chrome"},
            timestamp="2020-01-01T13:00:00Z",
        )
        _create_event(
            team=self.team,
            event="buy",
            distinct_id="person1",
            properties={"key": "val", "$browser": "Chrome"},
            timestamp="2020-01-01T15:00:00Z",
        )

        person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk, properties={"$country": "EE"})
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id="person2",
            properties={"key": "val", "$browser": "Safari"},
            timestamp="2020-01-02T14:00:00Z",
        )
        _create_event(
            team=self.team,
            event="play movie",
            distinct_id="person2",
            properties={"key": "val", "$browser": "Safari"},
            timestamp="2020-01-02T16:00:00Z",
        )
        return person1, person2

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
        results = ClickhouseFunnelPersons(filter, self.team)._exec_query()
        self.assertEqual(35, len(results))

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
        results = ClickhouseFunnelPersons(filter, self.team)._exec_query()
        self.assertEqual(5, len(results))

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
        results = ClickhouseFunnelPersons(filter, self.team)._exec_query()
        self.assertEqual(20, len(results))

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
        results = ClickhouseFunnelPersons(filter, self.team)._exec_query()
        self.assertEqual(10, len(results))

    def test_basic_offset(self):
        self._create_sample_data()
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
        results = ClickhouseFunnelPersons(filter, self.team)._exec_query()
        self.assertEqual(100, len(results))

        filter_offset = Filter(data={**data, "offset": 100,})
        results, _ = ClickhouseFunnelPersons(filter_offset, self.team).run()
        self.assertEqual(10, len(results))

    @test_with_materialized_columns(["$browser"])
    def test_first_step_breakdowns(self):
        person1, person2 = self._create_browser_breakdown_events()
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "interval": "day",
                "funnel_window_days": 7,
                "funnel_step": 1,
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
                "breakdown_type": "event",
                "breakdown": "$browser",
            }
        )
        results = ClickhouseFunnelPersons(filter, self.team)._exec_query()

        self.assertCountEqual([val[0] for val in results], [person1.uuid, person2.uuid])

        results = ClickhouseFunnelPersons(
            filter.with_data({"funnel_step_breakdown": "Chrome"}), self.team
        )._exec_query()

        self.assertCountEqual([val[0] for val in results], [person1.uuid])

        results = ClickhouseFunnelPersons(
            filter.with_data({"funnel_step_breakdown": "Safari"}), self.team
        )._exec_query()
        self.assertCountEqual([val[0] for val in results], [person2.uuid])

        results = ClickhouseFunnelPersons(
            filter.with_data({"funnel_step_breakdown": "Safari, Chrome"}), self.team
        )._exec_query()
        self.assertCountEqual([val[0] for val in results], [person2.uuid, person1.uuid])

    @test_with_materialized_columns(person_properties=["$country"])
    def test_first_step_breakdown_person(self):
        person1, person2 = self._create_browser_breakdown_events()
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "interval": "day",
                "funnel_window_days": 7,
                "funnel_step": 1,
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
                "breakdown_type": "person",
                "breakdown": "$country",
            }
        )

        results = ClickhouseFunnelPersons(filter, self.team)._exec_query()
        self.assertCountEqual([val[0] for val in results], [person1.uuid, person2.uuid])

        results = ClickhouseFunnelPersons(filter.with_data({"funnel_step_breakdown": "EE"}), self.team)._exec_query()
        self.assertCountEqual([val[0] for val in results], [person2.uuid])

        results = ClickhouseFunnelPersons(filter.with_data({"funnel_step_breakdown": "PL"}), self.team)._exec_query()
        self.assertCountEqual([val[0] for val in results], [person1.uuid])

    @test_with_materialized_columns(["$browser"], verify_no_jsonextract=False)
    def test_funnel_cohort_breakdown_persons(self):
        person = _create_person(distinct_ids=[f"person1"], team_id=self.team.pk, properties={"key": "value"})
        _create_event(
            team=self.team, event="sign up", distinct_id=f"person1", properties={}, timestamp="2020-01-02T12:00:00Z",
        )
        cohort = Cohort.objects.create(
            team=self.team,
            name="test_cohort",
            groups=[{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
        )
        filters = {
            "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2},],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
            "funnel_step": 1,
            "breakdown_type": "cohort",
            "breakdown": [cohort.pk],
        }
        filter = Filter(data=filters)
        results = ClickhouseFunnelPersons(filter, self.team)._exec_query()
        self.assertEqual(results[0][0], person.uuid)

    def test_first_step_with_session_recordings(self):
        filter = Filter(
            data={
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
        )
        with freeze_time("2021-04-20"):
            person = _create_person(distinct_ids=["user_1"], team=self.team)
        _create_event(event="step one", distinct_id="user_1", team=self.team, timestamp="2021-05-01 00:00:00")
        _create_event(event="step two", distinct_id="user_1", team=self.team, timestamp="2021-05-03 00:00:00")
        _create_event(event="step three", distinct_id="user_1", team=self.team, timestamp="2021-05-05 00:00:00")
        self._create_session_recording_snapshot("user_1", "444", datetime.fromisoformat("2021-05-03T01:00:00"))
        self._create_session_recording_snapshot("user_1", "444", datetime.fromisoformat("2021-05-03T01:01:00"))
        self._create_session_recording_snapshot("user_1", "444", datetime.fromisoformat("2021-05-03T01:02:00"))
        serialized_persons, _ = ClickhouseFunnelPersons(filter, self.team).run()
        self.assertListEqual(
            [
                {
                    "id": person.id,
                    "name": "user_1",
                    "distinct_ids": ["user_1"],
                    "properties": {},
                    "is_identified": False,
                    "created_at": "2021-04-20T00:00:00Z",
                    "uuid": str(person.uuid),
                    "session_recordings": [
                        {
                            "id": "444",
                            "person_id": str(person.uuid),
                            "start_time": "2021-05-03T01:00:00+00:00",
                            "end_time": "2021-05-03T01:02:00+00:00",
                            "recording_duration": 120,
                            "viewed": False,
                        }
                    ],
                }
            ],
            list(map(dict, serialized_persons)),
        )
