from datetime import datetime, timedelta
from typing import Any, Optional, cast
from uuid import UUID

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    snapshot_clickhouse_queries,
)

from django.utils import timezone

from posthog.schema import ActorsQuery, BaseMathType, FunnelsActorsQuery, FunnelsQuery

from posthog.constants import INSIGHT_FUNNELS
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.models import Cohort
from posthog.models.event.util import bulk_create_events
from posthog.models.person.util import bulk_create_persons
from posthog.models.team.team import Team
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.test.test_journeys import journeys_for

FORMAT_TIME = "%Y-%m-%d 00:00:00"
MAX_STEP_COLUMN = 0
COUNT_COLUMN = 1
PERSON_ID_COLUMN = 2


def get_actors(
    filters: dict[str, Any],
    team: Team,
    funnel_step: Optional[int] = None,
    funnel_custom_steps: Optional[list[int]] = None,
    funnel_step_breakdown: Optional[str | float | list[str | float]] = None,
    funnel_trends_drop_off: Optional[bool] = None,
    funnel_trends_entrance_period_start: Optional[str] = None,
    offset: Optional[int] = None,
    include_recordings: bool = False,
) -> list[list]:
    funnels_query = cast(FunnelsQuery, filter_to_query(filters))
    funnel_actors_query = FunnelsActorsQuery(
        source=funnels_query,
        funnelStep=funnel_step,
        funnelCustomSteps=funnel_custom_steps,
        funnelStepBreakdown=funnel_step_breakdown,
        funnelTrendsDropOff=funnel_trends_drop_off,
        funnelTrendsEntrancePeriodStart=funnel_trends_entrance_period_start,
        includeRecordings=include_recordings,
    )
    actors_query = ActorsQuery(
        source=funnel_actors_query,
        offset=offset,
        select=["id", "person", *(["matched_recordings"] if include_recordings else [])],
    )
    response = ActorsQueryRunner(query=actors_query, team=team).calculate()
    return response.results


class BaseTestFunnelPersons(ClickhouseTestMixin, APIBaseTest):
    __test__ = False

    def _create_sample_data_multiple_dropoffs(self):
        for i in range(35):
            bulk_create_persons([{"distinct_ids": [f"user_{i}"], "team_id": self.team.pk}])
        events = []
        for i in range(5):
            events.append(
                {
                    "event": "step one",
                    "distinct_id": f"user_{i}",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:00:00",
                }
            )
            events.append(
                {
                    "event": "step two",
                    "distinct_id": f"user_{i}",
                    "team": self.team,
                    "timestamp": "2021-05-03 00:00:00",
                }
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
                {
                    "event": "step one",
                    "distinct_id": f"user_{i}",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:00:00",
                }
            )
            events.append(
                {
                    "event": "step two",
                    "distinct_id": f"user_{i}",
                    "team": self.team,
                    "timestamp": "2021-05-03 00:00:00",
                }
            )

        for i in range(15, 35):
            events.append(
                {
                    "event": "step one",
                    "distinct_id": f"user_{i}",
                    "team": self.team,
                    "timestamp": "2021-05-01 00:00:00",
                }
            )
        bulk_create_events(events)

    def _create_browser_breakdown_events(self):
        person1 = _create_person(
            distinct_ids=["person1"],
            team_id=self.team.pk,
            properties={"$country": "PL"},
        )
        person2 = _create_person(
            distinct_ids=["person2"],
            team_id=self.team.pk,
            properties={"$country": "EE"},
        )
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
            create_people=False,
        )

        return person1, person2

    def test_first_step(self):
        self._create_sample_data_multiple_dropoffs()
        filters = {
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

        results = get_actors(filters, self.team, funnel_step=1)

        self.assertEqual(35, len(results))

    def test_last_step(self):
        self._create_sample_data_multiple_dropoffs()
        filters = {
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

        results = get_actors(filters, self.team, funnel_step=3)

        self.assertEqual(5, len(results))

    def test_second_step_dropoff(self):
        self._create_sample_data_multiple_dropoffs()
        filters = {
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

        results = get_actors(filters, self.team, funnel_step=-2)

        self.assertEqual(20, len(results))

    def test_last_step_dropoff(self):
        self._create_sample_data_multiple_dropoffs()
        filters = {
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

        results = get_actors(filters, self.team, funnel_step=-3)

        self.assertEqual(10, len(results))

    def _create_sample_data(self):
        for i in range(110):
            _create_person(distinct_ids=[f"user_{i}"], team=self.team)
            _create_event(
                event="step one",
                distinct_id=f"user_{i}",
                team=self.team,
                timestamp="2021-05-01 00:00:00",
            )
            _create_event(
                event="step two",
                distinct_id=f"user_{i}",
                team=self.team,
                timestamp="2021-05-03 00:00:00",
            )
            _create_event(
                event="step three",
                distinct_id=f"user_{i}",
                team=self.team,
                timestamp="2021-05-05 00:00:00",
            )

    def test_basic_offset(self):
        self._create_sample_data()
        filters = {
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

        # fetch first 100 people
        results = get_actors(filters, self.team, funnel_step=1)
        self.assertEqual(100, len(results))

        # fetch next 100 people (just 10 remaining)
        results = get_actors(filters, self.team, funnel_step=1, offset=100)
        self.assertEqual(10, len(results))

    def test_steps_with_custom_steps_parameter_are_equivalent_to_funnel_step(self):
        self._create_sample_data_multiple_dropoffs()
        filters = {
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

        parameters = [
            # funnelStep,  funnel_custom_steps, count
            (1, [1, 2, 3], 35),
            (2, [2, 3], 15),
            (3, [3], 5),
            (-2, [1], 20),
            (-3, [2], 10),
        ]

        for funnelStep, funnel_custom_steps, expected_count in parameters:
            results = get_actors(filters, self.team, funnel_step=funnelStep)

            new_results = get_actors(
                filters, self.team, funnel_step=funnelStep, funnel_custom_steps=funnel_custom_steps
            )

            self.assertEqual(new_results, results)
            self.assertEqual(len(results), expected_count)

    def test_steps_with_custom_steps_parameter_where_funnel_step_equivalence_isnt_possible(self):
        self._create_sample_data_multiple_dropoffs()
        filters = {
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

        parameters = [
            # funnel_custom_steps, count
            ([1, 2], 30),
            ([1, 3], 25),
            ([3, 1], 25),
            ([1, 3, 3, 1], 25),
        ]

        for funnel_custom_steps, expected_count in parameters:
            new_results = get_actors(filters, self.team, funnel_custom_steps=funnel_custom_steps)

            self.assertEqual(len(new_results), expected_count)

    def test_steps_with_custom_steps_parameter_overrides_funnel_step(self):
        self._create_sample_data_multiple_dropoffs()
        filters = {
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

        results = get_actors(
            filters, self.team, funnel_step=1, funnel_custom_steps=[3]
        )  # funnelStep=1 means custom steps = [1,2,3]

        self.assertEqual(len(results), 5)

    @also_test_with_materialized_columns(["$browser"])
    def test_first_step_breakdowns(self):
        person1, person2 = self._create_browser_breakdown_events()
        filters = {
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "interval": "day",
            "funnel_window_days": 7,
            "events": [
                {"id": "sign up", "order": 0},
                {"id": "play movie", "order": 1},
                {"id": "buy", "order": 2},
            ],
            "breakdown_type": "event",
            "breakdown": "$browser",
        }

        results = get_actors(filters, self.team, funnel_step=1)
        # self.assertCountEqual([val[0]["id"] for val in results], [person1.uuid, person2.uuid])
        self.assertCountEqual([results[0][0], results[1][0]], [person1.uuid, person2.uuid])

        results = get_actors(filters, self.team, funnel_step=1, funnel_step_breakdown=["Chrome"])
        # self.assertCountEqual([val[0]["id"] for val in results], [person1.uuid])
        self.assertCountEqual([results[0][0]], [person1.uuid])

        results = get_actors(filters, self.team, funnel_step=1, funnel_step_breakdown=["Safari"])
        # self.assertCountEqual([val[0]["id"] for val in results], [person2.uuid])
        self.assertCountEqual([results[0][0]], [person2.uuid])

    def test_first_step_breakdowns_with_multi_property_breakdown(self):
        person1, person2 = self._create_browser_breakdown_events()
        filters = {
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "interval": "day",
            "funnel_window_days": 7,
            "events": [
                {"id": "sign up", "order": 0},
                {"id": "play movie", "order": 1},
                {"id": "buy", "order": 2},
            ],
            "breakdown_type": "event",
            "breakdown": ["$browser", "$browser_version"],
        }

        results = get_actors(filters, self.team, funnel_step=1)
        # self.assertCountEqual([val[0]["id"] for val in results], [person1.uuid, person2.uuid])
        self.assertCountEqual([results[0][0], results[1][0]], [person1.uuid, person2.uuid])

        results = get_actors(filters, self.team, funnel_step=1, funnel_step_breakdown=["Chrome", "95"])
        # self.assertCountEqual([val[0]["id"] for val in results], [person1.uuid])
        self.assertCountEqual([results[0][0]], [person1.uuid])

        results = get_actors(filters, self.team, funnel_step=1, funnel_step_breakdown=["Safari", "14"])
        # self.assertCountEqual([val[0]["id"] for val in results], [person2.uuid])
        self.assertCountEqual([results[0][0]], [person2.uuid])

    @also_test_with_materialized_columns(person_properties=["$country"])
    def test_first_step_breakdown_person(self):
        person1, person2 = self._create_browser_breakdown_events()
        filters = {
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "interval": "day",
            "funnel_window_days": 7,
            "events": [
                {"id": "sign up", "order": 0},
                {"id": "play movie", "order": 1},
                {"id": "buy", "order": 2},
            ],
            "breakdown_type": "person",
            "breakdown": "$country",
        }

        results = get_actors(filters, self.team, funnel_step=1)
        # self.assertCountEqual([val[0]["id"] for val in results], [person1.uuid, person2.uuid])
        self.assertCountEqual([results[0][0], results[1][0]], [person1.uuid, person2.uuid])

        results = get_actors(filters, self.team, funnel_step=1, funnel_step_breakdown=["EE"])
        # self.assertCountEqual([val[0]["id"] for val in results], [person2.uuid])
        self.assertCountEqual([results[0][0]], [person2.uuid])

        # Check custom_steps give same answers for breakdowns
        custom_step_results = get_actors(
            filters, self.team, funnel_step=1, funnel_custom_steps=[1, 2, 3], funnel_step_breakdown=["EE"]
        )
        self.assertEqual(results, custom_step_results)

        results = get_actors(filters, self.team, funnel_step=1, funnel_step_breakdown=["PL"])
        # self.assertCountEqual([val[0]["id"] for val in results], [person1.uuid])
        self.assertCountEqual([results[0][0]], [person1.uuid])

        # Check custom_steps give same answers for breakdowns
        custom_step_results = get_actors(
            filters, self.team, funnel_step=1, funnel_custom_steps=[1, 2, 3], funnel_step_breakdown=["PL"]
        )
        self.assertEqual(results, custom_step_results)

    @also_test_with_materialized_columns(["$browser"], verify_no_jsonextract=False)
    def test_funnel_cohort_breakdown_persons(self):
        person = _create_person(distinct_ids=[f"person1"], team_id=self.team.pk, properties={"key": "value"})
        _create_event(
            team=self.team,
            event="sign up",
            distinct_id=f"person1",
            properties={},
            timestamp="2020-01-02T12:00:00Z",
        )
        cohort = Cohort.objects.create(
            team=self.team,
            name="test_cohort",
            groups=[{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
        )
        cohort.calculate_people_ch(pending_version=0)

        filters = {
            "events": [
                {"id": "sign up", "order": 0},
                {"id": "play movie", "order": 1},
                {"id": "buy", "order": 2},
            ],
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "funnel_window_days": 7,
            "breakdown_type": "cohort",
            "breakdown": [cohort.pk],
        }

        results = get_actors(filters, self.team, funnel_step=1)
        self.assertEqual(results[0][0], person.uuid)

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

        produce_replay_summary(
            team_id=self.team.pk,
            session_id="s2",
            distinct_id="user_1",
            first_timestamp=timezone.now() + timedelta(days=1),
        )

        # First event, but no recording
        filters = {
            "insight": INSIGHT_FUNNELS,
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

    def test_parses_step_breakdown_correctly(self):
        person1 = _create_person(
            distinct_ids=["person1"],
            team_id=self.team.pk,
            properties={"$country": "PL"},
        )
        journeys_for(
            {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "test''123"},
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 1, 13),
                        "properties": {"$browser": "test''123"},
                    },
                ],
            },
            self.team,
            create_people=False,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "interval": "day",
            "funnel_window_days": 7,
            "events": [
                {"id": "sign up", "order": 0},
                {"id": "play movie", "order": 1},
            ],
            "breakdown_type": "event",
            "breakdown": "$browser",
        }

        results = get_actors(filters, self.team, funnel_step=1, funnel_step_breakdown=["test'123"])
        self.assertCountEqual([results[0][0]], [person1.uuid])

    def test_first_time_math_basic(self):
        person1 = _create_person(
            distinct_ids=["person1"],
            team_id=self.team.pk,
        )
        journeys_for(
            {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                    },
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 12),
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 1, 13),
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 2, 13),
                    },
                ],
            },
            self.team,
            create_people=False,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "interval": "day",
            "funnel_window_days": 7,
            "events": [
                {"id": "sign up", "order": 0, "math": BaseMathType.FIRST_TIME_FOR_USER},
                {"id": "play movie", "order": 1},
            ],
            "breakdown_type": "event",
            "breakdown": "$browser",
        }

        results = get_actors(filters, self.team, funnel_step=1)
        self.assertCountEqual([results[0][0]], [person1.uuid])

        filters = {
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-02",
            "date_to": "2020-01-08",
            "interval": "day",
            "funnel_window_days": 7,
            "events": [
                {"id": "sign up", "order": 0, "math": BaseMathType.FIRST_TIME_FOR_USER},
                {"id": "play movie", "order": 1},
            ],
        }

        results = get_actors(filters, self.team, funnel_step=1)
        self.assertEqual(len(results), 0)

    def test_first_time_math_multiple_ids(self):
        _create_person(
            distinct_ids=["anon1", "person1"],
            team_id=self.team.pk,
        )
        _create_person(
            distinct_ids=["anon2", "person2"],
            team_id=self.team.pk,
        )
        journeys_for(
            {
                "anon1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                    },
                ],
                "person1": [
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 1, 13),
                    },
                ],
                "anon2": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2019, 1, 1, 12),
                    },
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                    },
                ],
                "person2": [
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 1, 13),
                    },
                ],
            },
            self.team,
            create_people=False,
        )

        filters = {
            "insight": INSIGHT_FUNNELS,
            "date_from": "2020-01-01",
            "date_to": "2020-01-08",
            "interval": "day",
            "funnel_window_days": 7,
            "events": [
                {"id": "sign up", "order": 0, "math": BaseMathType.FIRST_TIME_FOR_USER},
                {"id": "play movie", "order": 1},
            ],
        }

        results = get_actors(filters, self.team, funnel_step=1)
        self.assertEqual(len(results), 1)
        self.assertCountEqual(set(results[0][1]["distinct_ids"]), {"person1", "anon1"})

        filters = {
            "insight": INSIGHT_FUNNELS,
            "date_from": "2019-01-01",
            "date_to": "2020-01-08",
            "interval": "day",
            "funnel_window_days": 7,
            "events": [
                {"id": "sign up", "order": 0, "math": BaseMathType.FIRST_TIME_FOR_USER},
                {"id": "play movie", "order": 1},
            ],
            "breakdown_type": "event",
            "breakdown": "$browser",
        }

        results = get_actors(filters, self.team, funnel_step=1)
        self.assertEqual(len(results), 2)
        self.assertCountEqual(set(results[0][1]["distinct_ids"]), {"person1", "anon1"})
        self.assertCountEqual(set(results[1][1]["distinct_ids"]), {"person2", "anon2"})


class TestFunnelPersons(BaseTestFunnelPersons):
    __test__ = True
