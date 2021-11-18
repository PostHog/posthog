from datetime import datetime
from uuid import uuid4

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.funnels.funnel_persons import ClickhouseFunnelPersons
from ee.clickhouse.test.test_journeys import journeys_for
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
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


class TestFunnelPersons(ClickhouseTestMixin, APIBaseTest):
    def _create_sample_data_multiple_dropoffs(self):
        events_by_person = {}
        for i in range(5):
            user_id = f"user_{i}"
            events_by_person[user_id] = [
                {"event": "step one", "timestamp": datetime(2021, 5, 1)},
                {"event": "step two", "timestamp": datetime(2021, 5, 3)},
                {"event": "step three", "timestamp": datetime(2021, 5, 5)},
            ]

        for i in range(5, 15):
            user_id = f"user_{i}"
            events_by_person[user_id] = [
                {"event": "step one", "timestamp": datetime(2021, 5, 1)},
                {"event": "step two", "timestamp": datetime(2021, 5, 3)},
            ]

        for i in range(15, 35):
            user_id = f"user_{i}"
            events_by_person[user_id] = [
                {"event": "step one", "timestamp": datetime(2021, 5, 1)},
            ]

        journeys_for(events_by_person, self.team)

    def _create_browser_breakdown_events(self):
        person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk, properties={"$country": "PL"})
        person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk, properties={"$country": "EE"})
        journeys_for(
            {
                "person1": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 1, 12), "properties": {"$browser": "Chrome"}},
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 1, 13),
                        "properties": {"$browser": "Chrome"},
                    },
                    {"event": "buy", "timestamp": datetime(2020, 1, 1, 15), "properties": {"$browser": "Chrome"}},
                ],
                "person2": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 2, 14), "properties": {"$browser": "Safari"}},
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 2, 16),
                        "properties": {"$browser": "Safari"},
                    },
                ],
            },
            self.team,
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

    def _create_sample_data(self):
        for i in range(110):
            journeys_for(
                {
                    f"user_{i}": [
                        {"event": "step one", "timestamp": datetime(2021, 5, 1)},
                        {"event": "step two", "timestamp": datetime(2021, 5, 3)},
                        {"event": "step three", "timestamp": datetime(2021, 5, 5)},
                    ]
                },
                self.team,
            )

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
            results = ClickhouseFunnelPersons(filter, self.team)._exec_query()

            new_filter = base_filter.with_data({"funnel_custom_steps": custom_steps})
            new_results = ClickhouseFunnelPersons(new_filter, self.team)._exec_query()

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
            new_results = ClickhouseFunnelPersons(new_filter, self.team)._exec_query()

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

        results = ClickhouseFunnelPersons(Filter(data=data), self.team)._exec_query()

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

        # Check custom_steps give same answers for breakdowns
        custom_step_results = ClickhouseFunnelPersons(
            filter.with_data({"funnel_step_breakdown": "EE", "funnel_custom_steps": [1, 2, 3]}), self.team
        )._exec_query()
        self.assertEqual(results, custom_step_results)

        results = ClickhouseFunnelPersons(filter.with_data({"funnel_step_breakdown": "PL"}), self.team)._exec_query()
        self.assertCountEqual([val[0] for val in results], [person1.uuid])

        # Check custom_steps give same answers for breakdowns
        custom_step_results = ClickhouseFunnelPersons(
            filter.with_data({"funnel_step_breakdown": "PL", "funnel_custom_steps": [1, 2, 3]}), self.team
        )._exec_query()
        self.assertEqual(results, custom_step_results)

    @test_with_materialized_columns(["$browser"], verify_no_jsonextract=False)
    def test_funnel_cohort_breakdown_persons(self):
        person = _create_person(distinct_ids=[f"person1"], team_id=self.team.pk, properties={"key": "value"})
        journeys_for({"person1": [{"event": "sign up", "timestamp": datetime(2020, 1, 2, 12)},]}, self.team)
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
