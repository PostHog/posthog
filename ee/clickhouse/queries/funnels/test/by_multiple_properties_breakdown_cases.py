from typing import Dict, List, Tuple, Type, TypedDict

from ee.clickhouse.queries.funnels.funnel import ClickhouseFunnel
from posthog.constants import INSIGHT_FUNNELS
from posthog.models.filters import Filter
from posthog.test.base import APIBaseTest, test_with_materialized_columns


def funnel_breakdown_by_multi_property_test_factory(
    clickhouse_funnel: Type[ClickhouseFunnel], funnel_person, _create_event, _create_action, _create_person
):
    class TestFunnelMultiplePropertyBreakdown(APIBaseTest):
        def _get_people_at_step(self, filter, funnel_step, breakdown_value=None):
            person_filter = filter.with_data({"funnel_step": funnel_step, "funnel_step_breakdown": breakdown_value})
            result = funnel_person(person_filter, self.team)._exec_query()
            return [row[0] for row in result]

        class EventTestCase(TypedDict):
            event: str
            day: int
            hour: int

        def assertEqualWithPeopleInAnyOrder(self, expected: List[Dict], actual: List[Dict]):
            """
            When comparing two lists of funner results we are relying on arrays of people being in order for comparison
            The generated SQL does not order the people and so we cannot rely on that comprison
            This compares the lists without people, and then compares the people
            """

            def flatten(list_of_lists):
                return [item for sublist in list_of_lists for item in sublist]

            expected_copy = [e.copy() for e in expected]
            expected_people = [e.pop("people") for e in expected_copy]

            actual_copy = [a.copy() for a in actual]
            actual_people = [a.pop("people") for a in actual_copy]

            self.assertEqual(expected_copy, actual_copy)
            self.assertEqual(sorted(flatten(expected_people)), sorted(flatten(actual_people)))

        def a_journey_for(self, person: str, events: List[EventTestCase], breakdown_properties: List[Tuple]) -> None:
            for event in events:
                day = f"{event['day']:02d}"
                hour = f"{event['hour']:02d}"
                timestamp = f"2020-01-{day}T{hour}:00:00Z"

                properties = dict((k, v) for (k, v) in breakdown_properties)
                properties["key"] = "val"

                _create_event(
                    team=self.team,
                    event=event["event"],
                    distinct_id=person,
                    properties=properties,
                    timestamp=timestamp,
                )

        @test_with_materialized_columns(["$browser"], verify_no_jsonextract=False)
        def test_funnel_step_breakdown_event(self):

            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": ["$browser"],
            }

            filter = Filter(data=filters)
            funnel = clickhouse_funnel(filter, self.team)

            # event
            person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
            self.a_journey_for(
                "person1",
                [
                    {"event": "sign up", "day": 1, "hour": 12},
                    {"event": "play movie", "day": 1, "hour": 13},
                    {"event": "buy", "day": 1, "hour": 15},
                ],
                [("$browser", "Chrome")],
            )

            person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
            self.a_journey_for(
                "person2",
                [{"event": "sign up", "day": 2, "hour": 14}, {"event": "play movie", "day": 2, "hour": 16}],
                [("$browser", "Safari")],
            )

            person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
            self.a_journey_for("person3", [{"event": "sign up", "day": 2, "hour": 14}], [("$browser", "Safari")])

            result = funnel.run()
            self.assertEqualWithPeopleInAnyOrder(
                result[0],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "custom_name": None,
                        "order": 0,
                        "people": [person1.uuid]
                        if clickhouse_funnel == ClickhouseFunnel
                        else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Chrome",
                        "breakdown_value": "Chrome",
                    },
                    {
                        "action_id": "play movie",
                        "name": "play movie",
                        "custom_name": None,
                        "order": 1,
                        "people": [person1.uuid]
                        if clickhouse_funnel == ClickhouseFunnel
                        else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 3600.0,
                        "median_conversion_time": 3600.0,
                        "breakdown": "Chrome",
                        "breakdown_value": "Chrome",
                    },
                    {
                        "action_id": "buy",
                        "name": "buy",
                        "custom_name": None,
                        "order": 2,
                        "people": [person1.uuid]
                        if clickhouse_funnel == ClickhouseFunnel
                        else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 7200.0,
                        "median_conversion_time": 7200.0,
                        "breakdown": "Chrome",
                        "breakdown_value": "Chrome",
                    },
                ],
            )

            self.assertEqualWithPeopleInAnyOrder(
                result[1],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "custom_name": None,
                        "order": 0,
                        "people": [person2.uuid, person3.uuid]
                        if clickhouse_funnel == ClickhouseFunnel
                        else [],  # backwards compatibility
                        "count": 2,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari",
                        "breakdown_value": "Safari",
                    },
                    {
                        "action_id": "play movie",
                        "name": "play movie",
                        "custom_name": None,
                        "order": 1,
                        "people": [person2.uuid]
                        if clickhouse_funnel == ClickhouseFunnel
                        else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 7200.0,
                        "median_conversion_time": 7200.0,
                        "breakdown": "Safari",
                        "breakdown_value": "Safari",
                    },
                    {
                        "action_id": "buy",
                        "name": "buy",
                        "custom_name": None,
                        "order": 2,
                        "people": [],
                        "count": 0,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari",
                        "breakdown_value": "Safari",
                    },
                ],
            )

            self.assertCountEqual(self._get_people_at_step(filter, 1, "Chrome"), [person1.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 2, "Chrome"), [person1.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 1, "Safari"), [person2.uuid, person3.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 2, "Safari"), [person2.uuid])

        @test_with_materialized_columns(["$browser"], verify_no_jsonextract=False)
        def test_funnel_step_breakdown_event_by_two_properties(self):

            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": ["$browser", "$browser_version"],
            }

            filter = Filter(data=filters)
            funnel = clickhouse_funnel(filter, self.team)

            # event
            person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
            self.a_journey_for(
                "person1",
                [
                    {"event": "sign up", "day": 1, "hour": 12},
                    {"event": "play movie", "day": 1, "hour": 13},
                    {"event": "buy", "day": 1, "hour": 15},
                ],
                [("$browser", "Chrome"), ("$browser_version", "95")],
            )

            person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
            self.a_journey_for(
                "person2",
                [{"event": "sign up", "day": 2, "hour": 14}, {"event": "play movie", "day": 2, "hour": 16}],
                [("$browser", "Safari"), ("$browser_version", "14")],
            )

            person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
            self.a_journey_for(
                "person3",
                [{"event": "sign up", "day": 2, "hour": 14}],
                [("$browser", "Safari"), ("$browser_version", "15")],
            )

            person4 = _create_person(distinct_ids=["person4"], team_id=self.team.pk)
            self.a_journey_for(
                "person4",
                [{"event": "sign up", "day": 2, "hour": 15}],
                [("$browser", "Safari"), ("$browser_version", "15")],
            )

            result = funnel.run()

            self.assertEqualWithPeopleInAnyOrder(
                result[0],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "custom_name": None,
                        "order": 0,
                        "people": [person3.uuid, person4.uuid],
                        "count": 2,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari::15",
                        "breakdown_value": "Safari::15",
                    },
                    {
                        "action_id": "play movie",
                        "name": "play movie",
                        "custom_name": None,
                        "order": 1,
                        "people": [],
                        "count": 0,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari::15",
                        "breakdown_value": "Safari::15",
                    },
                    {
                        "action_id": "buy",
                        "name": "buy",
                        "custom_name": None,
                        "order": 2,
                        "people": [],
                        "count": 0,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari::15",
                        "breakdown_value": "Safari::15",
                    },
                ],
            )

            self.assertEqualWithPeopleInAnyOrder(
                result[1],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "custom_name": None,
                        "order": 0,
                        "people": [person1.uuid],
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Chrome::95",
                        "breakdown_value": "Chrome::95",
                    },
                    {
                        "action_id": "play movie",
                        "name": "play movie",
                        "custom_name": None,
                        "order": 1,
                        "people": [person1.uuid],
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 3600.0,
                        "median_conversion_time": 3600.0,
                        "breakdown": "Chrome::95",
                        "breakdown_value": "Chrome::95",
                    },
                    {
                        "action_id": "buy",
                        "name": "buy",
                        "custom_name": None,
                        "order": 2,
                        "people": [person1.uuid],
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 7200.0,
                        "median_conversion_time": 7200.0,
                        "breakdown": "Chrome::95",
                        "breakdown_value": "Chrome::95",
                    },
                ],
            )

            self.assertEqualWithPeopleInAnyOrder(
                result[2],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "custom_name": None,
                        "order": 0,
                        "people": [person2.uuid],
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari::14",
                        "breakdown_value": "Safari::14",
                    },
                    {
                        "action_id": "play movie",
                        "name": "play movie",
                        "custom_name": None,
                        "order": 1,
                        "people": [person2.uuid],
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 7200.0,
                        "median_conversion_time": 7200.0,
                        "breakdown": "Safari::14",
                        "breakdown_value": "Safari::14",
                    },
                    {
                        "action_id": "buy",
                        "name": "buy",
                        "custom_name": None,
                        "order": 2,
                        "people": [],
                        "count": 0,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari::14",
                        "breakdown_value": "Safari::14",
                    },
                ],
            )

            self.assertCountEqual(self._get_people_at_step(filter, 1, "Chrome::95"), [person1.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 2, "Chrome::95"), [person1.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 3, "Chrome::95"), [person1.uuid])

            self.assertCountEqual(self._get_people_at_step(filter, 1, "Safari::14"), [person2.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 2, "Safari::14"), [person2.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 3, "Safari::14"), [])

            self.assertCountEqual(self._get_people_at_step(filter, 1, "Safari::15"), [person3.uuid, person4.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 2, "Safari::15"), [])
            self.assertCountEqual(self._get_people_at_step(filter, 3, "Safari::15"), [])

        @test_with_materialized_columns(["$browser"])
        def test_funnel_step_breakdown_event_with_other(self):

            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": "$browser",
                "breakdown_limit": 1,
            }

            filter = Filter(data=filters)
            funnel = clickhouse_funnel(filter, self.team)

            # event
            person1 = _create_person(distinct_ids=["person1"], team_id=self.team.pk)
            self.a_journey_for(
                "person1",
                [
                    {"event": "sign up", "day": 1, "hour": 12},
                    {"event": "play movie", "day": 1, "hour": 13},
                    {"event": "buy", "day": 1, "hour": 15},
                ],
                [("$browser", "Chrome"), ("$browser_version", "95")],
            )

            person2 = _create_person(distinct_ids=["person2"], team_id=self.team.pk)
            self.a_journey_for(
                "person2",
                [{"event": "sign up", "day": 2, "hour": 14}, {"event": "play movie", "day": 2, "hour": 16}],
                [("$browser", "Safari"), ("$browser_version", "15")],
            )

            person3 = _create_person(distinct_ids=["person3"], team_id=self.team.pk)
            self.a_journey_for(
                "person3",
                [{"event": "sign up", "day": 2, "hour": 14}],
                [("$browser", "Safari"), ("$browser_version", "15")],
            )

            person4 = _create_person(distinct_ids=["person4"], team_id=self.team.pk)
            self.a_journey_for(
                "person4",
                [{"event": "sign up", "day": 2, "hour": 14}],
                [("$browser", "random"), ("$browser_version", "random")],
            )
            person5 = _create_person(distinct_ids=["person5"], team_id=self.team.pk)
            _create_event(
                team=self.team,
                event="sign up",
                distinct_id="person5",
                properties={"key": "val", "$browser": "another one"},
                timestamp="2020-01-02T15:00:00Z",
            )
            self.a_journey_for(
                "person5",
                [{"event": "sign up", "day": 2, "hour": 15}],
                [("$browser", "another one"), ("$browser_version", "another one")],
            )
            result = funnel.run()

            people = result[0][0].pop("people")
            self.assertCountEqual(
                people, [person1.uuid, person4.uuid, person5.uuid] if clickhouse_funnel == ClickhouseFunnel else []
            )

            self.assertEqual(
                result[0],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "custom_name": None,
                        "order": 0,
                        # popped people because flakey ordering for assertEqual
                        "count": 3,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Other",
                        "breakdown_value": "Other",
                    },
                    {
                        "action_id": "play movie",
                        "name": "play movie",
                        "custom_name": None,
                        "order": 1,
                        "people": [person1.uuid]
                        if clickhouse_funnel == ClickhouseFunnel
                        else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 3600.0,
                        "median_conversion_time": 3600.0,
                        "breakdown": "Other",
                        "breakdown_value": "Other",
                    },
                    {
                        "action_id": "buy",
                        "name": "buy",
                        "custom_name": None,
                        "order": 2,
                        "people": [person1.uuid]
                        if clickhouse_funnel == ClickhouseFunnel
                        else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 7200.0,
                        "median_conversion_time": 7200.0,
                        "breakdown": "Other",
                        "breakdown_value": "Other",
                    },
                ],
            )
            self.assertCountEqual(
                self._get_people_at_step(filter, 1, "Other"), [person1.uuid, person4.uuid, person5.uuid]
            )
            self.assertCountEqual(self._get_people_at_step(filter, 2, "Other"), [person1.uuid])

            self.assertEqual(
                result[1],
                [
                    {
                        "action_id": "sign up",
                        "name": "sign up",
                        "custom_name": None,
                        "order": 0,
                        "people": [person2.uuid, person3.uuid]
                        if clickhouse_funnel == ClickhouseFunnel
                        else [],  # backwards compatibility
                        "count": 2,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari",
                        "breakdown_value": "Safari",
                    },
                    {
                        "action_id": "play movie",
                        "name": "play movie",
                        "custom_name": None,
                        "order": 1,
                        "people": [person2.uuid]
                        if clickhouse_funnel == ClickhouseFunnel
                        else [],  # backwards compatibility
                        "count": 1,
                        "type": "events",
                        "average_conversion_time": 7200.0,
                        "median_conversion_time": 7200.0,
                        "breakdown": "Safari",
                        "breakdown_value": "Safari",
                    },
                    {
                        "action_id": "buy",
                        "name": "buy",
                        "custom_name": None,
                        "order": 2,
                        "people": [],
                        "count": 0,
                        "type": "events",
                        "average_conversion_time": None,
                        "median_conversion_time": None,
                        "breakdown": "Safari",
                        "breakdown_value": "Safari",
                    },
                ],
            )

            self.assertCountEqual(self._get_people_at_step(filter, 1, "Safari"), [person2.uuid, person3.uuid])
            self.assertCountEqual(self._get_people_at_step(filter, 2, "Safari"), [person2.uuid])

        @test_with_materialized_columns(["some_breakdown_val"])
        def test_funnel_step_custom_breakdown_limit_with_nulls_with_one_property(self):

            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown_limit": 3,
                "breakdown": ["some_breakdown_val"],
            }

            filter = Filter(data=filters)
            funnel = clickhouse_funnel(filter, self.team)

            for num in range(5):
                for i in range(num):
                    person = f"person_{num}_{i}"
                    _create_person(distinct_ids=[person], team_id=self.team.pk)
                    self.a_journey_for(
                        person,
                        [
                            {"event": "sign up", "day": 1, "hour": 12},
                            {"event": "play movie", "day": 1, "hour": 13},
                            {"event": "buy", "day": 1, "hour": 15},
                        ],
                        [("some_breakdown_val", num)],
                    )

            # no breakdown value for this guy
            person0 = _create_person(distinct_ids=[f"person_null"], team_id=self.team.pk)
            self.a_journey_for(
                "person_null",
                [
                    {"event": "sign up", "day": 1, "hour": 12},
                    {"event": "play movie", "day": 1, "hour": 13},
                    {"event": "buy", "day": 1, "hour": 15},
                ],
                [],
            )

            result = funnel.run()

            breakdown_vals = sorted([res[0]["breakdown"] for res in result])
            self.assertEqual(["2", "3", "4", "Other"], breakdown_vals)
            # skipped 1 and '' because the limit was 3.
            self.assertTrue(person0.uuid in self._get_people_at_step(filter, 1, "Other"))

        @test_with_materialized_columns(["some_breakdown_val"], verify_no_jsonextract=False)
        def test_funnel_step_custom_breakdown_limit_with_nulls_with_two_properties(self):

            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "play movie", "order": 1}, {"id": "buy", "order": 2}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown_limit": 3,
                "breakdown": ["some_breakdown_val", "another_breakdown_val"],
            }

            filter = Filter(data=filters)
            funnel = clickhouse_funnel(filter, self.team)

            for num in range(5):
                for i in range(num):
                    person = f"person_{num}_{i}"
                    _create_person(distinct_ids=[person], team_id=self.team.pk)
                    self.a_journey_for(
                        person,
                        [
                            {"event": "sign up", "day": 1, "hour": 12},
                            {"event": "play movie", "day": 1, "hour": 13},
                            {"event": "buy", "day": 1, "hour": 15},
                        ],
                        [("some_breakdown_val", num), ("another_breakdown_val", num + 1)],
                    )

            # no breakdown value for this guy
            person0 = _create_person(distinct_ids=[f"person_null"], team_id=self.team.pk)
            self.a_journey_for(
                "person_null",
                [
                    {"event": "sign up", "day": 1, "hour": 12},
                    {"event": "play movie", "day": 1, "hour": 13},
                    {"event": "buy", "day": 1, "hour": 15},
                ],
                [],
            )

            result = funnel.run()

            breakdown_vals = sorted([res[0]["breakdown"] for res in result])
            self.assertEqual(["2::3", "3::4", "4::5", "Other"], breakdown_vals)  # NOSONAR python:S1313
            # skipped 1 and '' because the limit was 3.
            self.assertTrue(person0.uuid in self._get_people_at_step(filter, 1, "Other"))

    return TestFunnelMultiplePropertyBreakdown
