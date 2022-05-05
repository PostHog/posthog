from datetime import datetime, timedelta
from uuid import UUID, uuid4

from django.utils import timezone
from freezegun import freeze_time

from ee.clickhouse.models.event import bulk_create_events
from ee.clickhouse.models.person import bulk_create_persons
from ee.clickhouse.models.session_recording_event import create_session_recording_event
from ee.clickhouse.queries.funnels.funnel_persons import ClickhouseFunnelActors
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.constants import INSIGHT_FUNNELS
from posthog.models import Cohort, Filter
from posthog.test.base import APIBaseTest, _create_event, _create_person, test_with_materialized_columns

FORMAT_TIME = "%Y-%m-%d 00:00:00"
MAX_STEP_COLUMN = 0
COUNT_COLUMN = 1
PERSON_ID_COLUMN = 2


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


class TestFunnelPersons(ClickhouseTestMixin, APIBaseTest):
    def _create_sample_data_multiple_dropoffs(self):
        for i in range(35):
            bulk_create_persons([{"distinct_ids": [f"user_{i}"], "team_id": self.team.pk}])
        events = []
        for i in range(5):
            events.append(
                {"event": "step one", "distinct_id": f"user_{i}", "team": self.team, "timestamp": "2021-05-01 00:00:00"}
            )
            events.append(
                {"event": "step two", "distinct_id": f"user_{i}", "team": self.team, "timestamp": "2021-05-03 00:00:00"}
            )
            events.append(
                {
                    "event": "step three",
                    "distinct_id": f"user_{i}",
                    "team": self.team,
                    "timestamp": "2021-05-05 00:00:00",
                }
            )

        for i in range(5, 15):
            events.append(
                {"event": "step one", "distinct_id": f"user_{i}", "team": self.team, "timestamp": "2021-05-01 00:00:00"}
            )
            events.append(
                {"event": "step two", "distinct_id": f"user_{i}", "team": self.team, "timestamp": "2021-05-03 00:00:00"}
            )

        for i in range(15, 35):
            events.append(
                {"event": "step one", "distinct_id": f"user_{i}", "team": self.team, "timestamp": "2021-05-01 00:00:00"}
            )
        bulk_create_events(events)

    def _create_browser_breakdown_events(self):
        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk, properties={"$country": "PL"})
        person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk, properties={"$country": "EE"})
        journeys_for(
            {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome", "$browser_version": "95"},
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 1, 13),
                        "properties": {"$browser": "Chrome", "$browser_version": "95"},
                    },
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 1, 15),
                        "properties": {"$browser": "Chrome", "$browser_version": "95"},
                    },
                ],
                "person2": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Safari", "$browser_version": "14"},
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 2, 16),
                        "properties": {"$browser": "Safari", "$browser_version": "14"},
                    },
                ],
            },
            self.team,
        )

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
        _, results = ClickhouseFunnelActors(filter, self.team).get_actors()
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
        _, results = ClickhouseFunnelActors(filter, self.team).get_actors()
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
        _, results = ClickhouseFunnelActors(filter, self.team).get_actors()
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
        _, results = ClickhouseFunnelActors(filter, self.team).get_actors()
        self.assertEqual(10, len(results))

    def _create_sample_data(self):
        for i in range(110):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(event="step one", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-01 00:00:00")
            _create_event(event="step two", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-03 00:00:00")
            _create_event(event="step three", distinct_id=f"user_{i}", team=self.team, timestamp="2021-05-05 00:00:00")

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
        _, results = ClickhouseFunnelActors(filter, self.team).get_actors()
        self.assertEqual(100, len(results))

        filter_offset = Filter(data={**data, "offset": 100,})
        _, results = ClickhouseFunnelActors(filter_offset, self.team).get_actors()
        self.assertEqual(10, len(results))

    def test_steps_with_custom_steps_parameter_are_equivalent_to_funnel_step(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
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
        base_filter = Filter(data=data)

        parameters = [
            #  funnel_step,  custom_steps, expected_results
            (1, [1, 2, 3], 35),
            (2, [2, 3], 15),
            (3, [3], 5),
            (-2, [1], 20),
            (-3, [2], 10),
        ]

        for funnel_step, custom_steps, expected_count in parameters:
            filter = base_filter.with_data({"funnel_step": funnel_step})
            _, results = ClickhouseFunnelActors(filter, self.team).get_actors()

            new_filter = base_filter.with_data({"funnel_custom_steps": custom_steps})
            _, new_results = ClickhouseFunnelActors(new_filter, self.team).get_actors()

            self.assertEqual(new_results, results)
            self.assertEqual(len(results), expected_count)

    def test_steps_with_custom_steps_parameter_where_funnel_step_equivalence_isnt_possible(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
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
        base_filter = Filter(data=data)

        parameters = [
            # custom_steps, expected_results
            ([1, 2], 30),
            ([1, 3], 25),
            ([3, 1], 25),
            ([1, 3, 3, 1], 25),
        ]

        for custom_steps, expected_count in parameters:
            new_filter = base_filter.with_data({"funnel_custom_steps": custom_steps})
            _, new_results = ClickhouseFunnelActors(new_filter, self.team).get_actors()

            self.assertEqual(len(new_results), expected_count)

    def test_steps_with_custom_steps_parameter_overrides_funnel_step(self):
        self._create_sample_data_multiple_dropoffs()
        data = {
            "insight": INSIGHT_FUNNELS,
            "interval": "day",
            "date_from": "2021-05-01 00:00:00",
            "date_to": "2021-05-07 00:00:00",
            "funnel_window_days": 7,
            "funnel_step": 1,  # means custom steps = [1,2,3]
            "funnel_custom_steps": [3],
            "events": [
                {"id": "step one", "order": 0},
                {"id": "step two", "order": 1},
                {"id": "step three", "order": 2},
            ],
        }

        _, results = ClickhouseFunnelActors(Filter(data=data), self.team).get_actors()

        self.assertEqual(len(results), 5)

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
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2}],
                "breakdown_type": "event",
                "breakdown": "$browser",
            }
        )
        _, results = ClickhouseFunnelActors(filter, self.team).get_actors()

        self.assertCountEqual([val["id"] for val in results], [person1.uuid, person2.uuid])

        _, results = ClickhouseFunnelActors(
            filter.with_data({"funnel_step_breakdown": "Chrome"}), self.team
        ).get_actors()

        self.assertCountEqual([val["id"] for val in results], [person1.uuid])

        _, results = ClickhouseFunnelActors(
            filter.with_data({"funnel_step_breakdown": "Safari"}), self.team
        ).get_actors()

        self.assertCountEqual([val["id"] for val in results], [person2.uuid])

    def test_first_step_breakdowns_with_multi_property_breakdown(self):
        person1, person2 = self._create_browser_breakdown_events()
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "interval": "day",
                "funnel_window_days": 7,
                "funnel_step": 1,
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2}],
                "breakdown_type": "event",
                "breakdown": ["$browser", "$browser_version"],
            }
        )
        _, results = ClickhouseFunnelActors(filter, self.team).get_actors()

        self.assertCountEqual([val["id"] for val in results], [person1.uuid, person2.uuid])

        _, results = ClickhouseFunnelActors(
            filter.with_data({"funnel_step_breakdown": "Chrome"}), self.team
        ).get_actors()

        self.assertCountEqual([val["id"] for val in results], [person1.uuid])

        _, results = ClickhouseFunnelActors(
            filter.with_data({"funnel_step_breakdown": "Safari"}), self.team
        ).get_actors()
        self.assertCountEqual([val["id"] for val in results], [person2.uuid])

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
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2}],
                "breakdown_type": "person",
                "breakdown": "$country",
            }
        )

        _, results = ClickhouseFunnelActors(filter, self.team).get_actors()
        self.assertCountEqual([val["id"] for val in results], [person1.uuid, person2.uuid])

        _, results = ClickhouseFunnelActors(filter.with_data({"funnel_step_breakdown": "EE"}), self.team).get_actors()
        self.assertCountEqual([val["id"] for val in results], [person2.uuid])

        # Check custom_steps give same answers for breakdowns
        _, custom_step_results = ClickhouseFunnelActors(
            filter.with_data({"funnel_step_breakdown": "EE", "funnel_custom_steps": [1, 2, 3]}), self.team
        ).get_actors()
        self.assertEqual(results, custom_step_results)

        _, results = ClickhouseFunnelActors(filter.with_data({"funnel_step_breakdown": "PL"}), self.team).get_actors()
        self.assertCountEqual([val["id"] for val in results], [person1.uuid])

        # Check custom_steps give same answers for breakdowns
        _, custom_step_results = ClickhouseFunnelActors(
            filter.with_data({"funnel_step_breakdown": "PL", "funnel_custom_steps": [1, 2, 3]}), self.team
        ).get_actors()
        self.assertEqual(results, custom_step_results)

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
            "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2}],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
            "funnel_step": 1,
            "breakdown_type": "cohort",
            "breakdown": [cohort.pk],
        }
        filter = Filter(data=filters)
        _, results = ClickhouseFunnelActors(filter, self.team).get_actors()
        self.assertEqual(results[0]["id"], person.uuid)

    @snapshot_clickhouse_queries
    @freeze_time("2021-01-02 00:00:00.000Z")
    def test_funnel_person_recordings(self):
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
        _create_session_recording_event(self.team.pk, "user_1", "s2", datetime(2021, 1, 3, 0, 0, 0))

        # First event, but no recording
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
                "include_recordings": "true",
            }
        )
        _, results = ClickhouseFunnelActors(filter, self.team).get_actors()
        self.assertEqual(results[0]["id"], p1.uuid)
        self.assertEqual(results[0]["matched_recordings"], [])

        # Second event, with recording
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "date_from": "2021-01-01",
                "date_to": "2021-01-08",
                "interval": "day",
                "funnel_window_days": 7,
                "funnel_step": 2,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
                "include_recordings": "true",
            }
        )
        _, results = ClickhouseFunnelActors(filter, self.team).get_actors()
        self.assertEqual(results[0]["id"], p1.uuid)
        self.assertEqual(
            results[0]["matched_recordings"],
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
        filter = Filter(
            data={
                "insight": INSIGHT_FUNNELS,
                "date_from": "2021-01-01",
                "date_to": "2021-01-08",
                "interval": "day",
                "funnel_window_days": 7,
                "funnel_step": -3,
                "events": [
                    {"id": "step one", "order": 0},
                    {"id": "step two", "order": 1},
                    {"id": "step three", "order": 2},
                ],
                "include_recordings": "true",
            }
        )
        _, results = ClickhouseFunnelActors(filter, self.team).get_actors()
        self.assertEqual(results[0]["id"], p1.uuid)
        self.assertEqual(
            results[0]["matched_recordings"],
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
