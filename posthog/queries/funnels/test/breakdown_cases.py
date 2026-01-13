import uuid
from dataclasses import dataclass
from datetime import datetime
from string import ascii_lowercase
from typing import Any, Literal, Optional, Union

from posthog.test.base import APIBaseTest, also_test_with_materialized_columns, snapshot_clickhouse_queries

from posthog.constants import INSIGHT_FUNNELS
from posthog.models.cohort import Cohort
from posthog.models.filters import Filter
from posthog.queries.breakdown_props import ALL_USERS_COHORT_ID
from posthog.queries.funnels.funnel_unordered import ClickhouseFunnelUnordered
from posthog.test.test_journeys import journeys_for


@dataclass(frozen=True)
class FunnelStepResult:
    name: str
    count: int
    breakdown: Union[list[str], str]
    average_conversion_time: Optional[float] = None
    median_conversion_time: Optional[float] = None
    type: Literal["events", "actions"] = "events"
    action_id: Optional[str] = None


def funnel_breakdown_test_factory(Funnel, FunnelPerson, _create_event, _create_action, _create_person):
    class TestFunnelBreakdown(APIBaseTest):
        def _get_actor_ids_at_step(self, filter, funnel_step, breakdown_value=None):
            person_filter = filter.shallow_clone({"funnel_step": funnel_step, "funnel_step_breakdown": breakdown_value})
            _, serialized_result, _ = FunnelPerson(person_filter, self.team).get_actors()

            return [val["id"] for val in serialized_result]

        def _assert_funnel_breakdown_result_is_correct(self, result, steps: list[FunnelStepResult]):
            def funnel_result(step: FunnelStepResult, order: int) -> dict[str, Any]:
                return {
                    "action_id": step.name if step.type == "events" else step.action_id,
                    "name": step.name,
                    "custom_name": None,
                    "order": order,
                    "people": [],
                    "count": step.count,
                    "type": step.type,
                    "average_conversion_time": step.average_conversion_time,
                    "median_conversion_time": step.median_conversion_time,
                    "breakdown": step.breakdown,
                    "breakdown_value": step.breakdown,
                    **(
                        {
                            "action_id": None,
                            "name": f"Completed {order+1} step{'s' if order > 0 else ''}",
                        }
                        if Funnel == ClickhouseFunnelUnordered
                        else {}
                    ),
                }

            step_results = []
            for index, step_result in enumerate(steps):
                step_results.append(funnel_result(step_result, index))

            assert_funnel_results_equal(result, step_results)

        @also_test_with_materialized_columns(["$browser", "$browser_version"])
        def test_funnel_step_multi_property_breakdown_event(self):
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
                "breakdown_type": "event",
                "breakdown": ["$browser", "$browser_version"],
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            journey = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {
                            "key": "val",
                            "$browser": "Chrome",
                            "$browser_version": 95,
                        },
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 1, 13),
                        "properties": {
                            "key": "val",
                            "$browser": "Chrome",
                            "$browser_version": 95,
                        },
                    },
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 1, 15),
                        "properties": {
                            "key": "val",
                            "$browser": "Chrome",
                            "$browser_version": 95,
                        },
                    },
                ],
                "person2": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {
                            "key": "val",
                            "$browser": "Safari",
                            "$browser_version": 15,
                        },
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 2, 16),
                        "properties": {
                            "key": "val",
                            "$browser": "Safari",
                            "$browser_version": 15,
                        },
                    },
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {
                            "key": "val",
                            "$browser": "Safari",
                            "$browser_version": 14,
                        },
                    }
                ],
            }

            people = journeys_for(events_by_person=journey, team=self.team)

            result = funnel.run()

            self._assert_funnel_breakdown_result_is_correct(
                result[2],
                [
                    FunnelStepResult(name="sign up", breakdown=["Safari", "14"], count=1),
                    FunnelStepResult(name="play movie", breakdown=["Safari", "14"], count=0),
                    FunnelStepResult(name="buy", breakdown=["Safari", "14"], count=0),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, ["Safari", "14"]),
                [people["person3"].uuid],
            )
            self.assertCountEqual(self._get_actor_ids_at_step(filter, 2, ["Safari", "14"]), [])

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", breakdown=["Safari", "15"], count=1),
                    FunnelStepResult(
                        name="play movie",
                        breakdown=["Safari", "15"],
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                    FunnelStepResult(name="buy", breakdown=["Safari", "15"], count=0),
                ],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, ["Safari", "15"]),
                [people["person2"].uuid],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2, ["Safari", "15"]),
                [people["person2"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown=["Chrome", "95"], count=1),
                    FunnelStepResult(
                        name="play movie",
                        breakdown=["Chrome", "95"],
                        count=1,
                        average_conversion_time=3600.0,
                        median_conversion_time=3600.0,
                    ),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Chrome", "95"],
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                ],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, ["Chrome", "95"]),
                [people["person1"].uuid],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2, ["Chrome", "95"]),
                [people["person1"].uuid],
            )

        @also_test_with_materialized_columns(["$browser"])
        def test_funnel_step_breakdown_event_with_string_only_breakdown(self):
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
                "breakdown_type": "event",
                "breakdown": "$browser",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            journey = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"key": "val", "$browser": "Chrome"},
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 1, 13),
                        "properties": {"key": "val", "$browser": "Chrome"},
                    },
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 1, 15),
                        "properties": {"key": "val", "$browser": "Chrome"},
                    },
                ],
                "person2": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"key": "val", "$browser": "Safari"},
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 2, 16),
                        "properties": {"key": "val", "$browser": "Safari"},
                    },
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"key": "val", "$browser": "Safari"},
                    }
                ],
            }

            people = journeys_for(events_by_person=journey, team=self.team)

            result = funnel.run()

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown=["Chrome"], count=1),
                    FunnelStepResult(
                        name="play movie",
                        breakdown=["Chrome"],
                        count=1,
                        average_conversion_time=3600.0,
                        median_conversion_time=3600.0,
                    ),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Chrome"],
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                ],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Chrome"),
                [people["person1"].uuid],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2, "Chrome"),
                [people["person1"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", breakdown=["Safari"], count=2),
                    FunnelStepResult(
                        name="play movie",
                        breakdown=["Safari"],
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                    FunnelStepResult(name="buy", breakdown=["Safari"], count=0),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Safari"),
                [people["person2"].uuid, people["person3"].uuid],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2, "Safari"),
                [people["person2"].uuid],
            )

        @also_test_with_materialized_columns(["$browser"])
        def test_funnel_step_breakdown_event(self):
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
                "breakdown_type": "event",
                "breakdown": ["$browser"],
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            journey = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"key": "val", "$browser": "Chrome"},
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 1, 13),
                        "properties": {"key": "val", "$browser": "Chrome"},
                    },
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 1, 15),
                        "properties": {"key": "val", "$browser": "Chrome"},
                    },
                ],
                "person2": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"key": "val", "$browser": "Safari"},
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 2, 16),
                        "properties": {"key": "val", "$browser": "Safari"},
                    },
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"key": "val", "$browser": "Safari"},
                    }
                ],
            }

            people = journeys_for(events_by_person=journey, team=self.team)

            result = funnel.run()

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown=["Chrome"], count=1),
                    FunnelStepResult(
                        name="play movie",
                        breakdown=["Chrome"],
                        count=1,
                        average_conversion_time=3600.0,
                        median_conversion_time=3600.0,
                    ),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Chrome"],
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                ],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Chrome"),
                [people["person1"].uuid],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2, "Chrome"),
                [people["person1"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", breakdown=["Safari"], count=2),
                    FunnelStepResult(
                        name="play movie",
                        breakdown=["Safari"],
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                    FunnelStepResult(name="buy", breakdown=["Safari"], count=0),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Safari"),
                [people["person2"].uuid, people["person3"].uuid],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2, "Safari"),
                [people["person2"].uuid],
            )

        @also_test_with_materialized_columns(["$browser"])
        def test_funnel_step_breakdown_event_with_other(self):
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
                "breakdown_type": "event",
                "breakdown": ["$browser"],
                "breakdown_limit": 1,
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            events_by_person = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 1, 13),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 1, 15),
                        "properties": {"$browser": "Chrome"},
                    },
                ],
                "person2": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Safari"},
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 2, 16),
                        "properties": {"$browser": "Safari"},
                    },
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Safari"},
                    }
                ],
                "person4": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "random"},
                    }
                ],
                "person5": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 15),
                        "properties": {"$browser": "another one"},
                    }
                ],
            }

            people = journeys_for(events_by_person, self.team)

            result = funnel.run()
            result = sort_breakdown_funnel_results(result)

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", breakdown=["Safari"], count=2),
                    FunnelStepResult(
                        name="play movie",
                        breakdown=["Safari"],
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                    FunnelStepResult(name="buy", breakdown=["Safari"], count=0),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Safari"),
                [people["person2"].uuid, people["person3"].uuid],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2, "Safari"),
                [people["person2"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown=["Other"], count=3),
                    FunnelStepResult(
                        name="play movie",
                        breakdown=["Other"],
                        count=1,
                        average_conversion_time=3600.0,
                        median_conversion_time=3600.0,
                    ),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Other"],
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Other"),
                [
                    people["person1"].uuid,
                    people["person4"].uuid,
                    people["person5"].uuid,
                ],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2, "Other"),
                [people["person1"].uuid],
            )

        @also_test_with_materialized_columns(["$browser"])
        def test_funnel_step_breakdown_event_no_type(self):
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
                "breakdown": ["$browser"],
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            events_by_person = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 1, 13),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 1, 15),
                        "properties": {"$browser": "Chrome"},
                    },
                ],
                "person2": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Safari"},
                    },
                    {
                        "event": "play movie",
                        "timestamp": datetime(2020, 1, 2, 16),
                        "properties": {"$browser": "Safari"},
                    },
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Safari"},
                    }
                ],
            }

            people = journeys_for(events_by_person, self.team)

            result = funnel.run()

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown=["Chrome"], count=1),
                    FunnelStepResult(
                        name="play movie",
                        breakdown=["Chrome"],
                        count=1,
                        average_conversion_time=3600.0,
                        median_conversion_time=3600.0,
                    ),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Chrome"],
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Chrome"),
                [people["person1"].uuid],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2, "Chrome"),
                [people["person1"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", breakdown=["Safari"], count=2),
                    FunnelStepResult(
                        name="play movie",
                        breakdown=["Safari"],
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                    FunnelStepResult(name="buy", breakdown=["Safari"], count=0),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Safari"),
                [people["person2"].uuid, people["person3"].uuid],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2, "Safari"),
                [people["person2"].uuid],
            )

        @also_test_with_materialized_columns(person_properties=["$browser"])
        def test_funnel_step_breakdown_person(self):
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
                "breakdown_type": "person",
                "breakdown": ["$browser"],
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            person1 = _create_person(
                distinct_ids=["person1"],
                team_id=self.team.pk,
                properties={"$browser": "Chrome"},
            )
            person2 = _create_person(
                distinct_ids=["person2"],
                team_id=self.team.pk,
                properties={"$browser": "Safari"},
            )

            peoples_journeys = {
                "person1": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 1, 12)},
                    {"event": "play movie", "timestamp": datetime(2020, 1, 1, 13)},
                    {"event": "buy", "timestamp": datetime(2020, 1, 1, 15)},
                ],
                "person2": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 2, 14)},
                    {"event": "play movie", "timestamp": datetime(2020, 1, 2, 16)},
                ],
            }
            journeys_for(peoples_journeys, self.team, create_people=False)

            result = funnel.run()

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown=["Chrome"], count=1),
                    FunnelStepResult(
                        name="play movie",
                        breakdown=["Chrome"],
                        count=1,
                        average_conversion_time=3600.0,
                        median_conversion_time=3600.0,
                    ),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Chrome"],
                        count=1,
                        average_conversion_time=7200,
                        median_conversion_time=7200,
                    ),
                ],
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "Chrome"), [person1.uuid])
            self.assertCountEqual(self._get_actor_ids_at_step(filter, 2, "Chrome"), [person1.uuid])

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", breakdown=["Safari"], count=1),
                    FunnelStepResult(
                        name="play movie",
                        breakdown=["Safari"],
                        count=1,
                        average_conversion_time=7200.0,
                        median_conversion_time=7200.0,
                    ),
                    FunnelStepResult(name="buy", breakdown=["Safari"], count=0),
                ],
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "Safari"), [person2.uuid])
            self.assertCountEqual(self._get_actor_ids_at_step(filter, 3, "Safari"), [])

        @also_test_with_materialized_columns(["some_breakdown_val"])
        def test_funnel_step_breakdown_limit(self):
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
                "breakdown_type": "event",
                "breakdown": ["some_breakdown_val"],
                "breakdown_limit": 5,
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            events_by_person = {}
            for num in range(10):
                for i in range(num):
                    person_id = f"person_{num}_{i}"
                    events_by_person[person_id] = [
                        {
                            "event": "sign up",
                            "timestamp": datetime(2020, 1, 1, 12),
                            "properties": {"some_breakdown_val": str(num)},
                        },
                        {
                            "event": "play movie",
                            "timestamp": datetime(2020, 1, 1, 13),
                            "properties": {"some_breakdown_val": str(num)},
                        },
                        {
                            "event": "buy",
                            "timestamp": datetime(2020, 1, 1, 15),
                            "properties": {"some_breakdown_val": str(num)},
                        },
                    ]
            journeys_for(events_by_person, self.team)

            result = funnel.run()

            # assert that we give 5 at a time at most and that those values are the most popular ones
            breakdown_vals = sorted([res[0]["breakdown"] for res in result])
            self.assertEqual([["5"], ["6"], ["7"], ["8"], ["9"], ["Other"]], breakdown_vals)

        @also_test_with_materialized_columns(["some_breakdown_val"])
        def test_funnel_step_custom_breakdown_limit_with_nulls(self):
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
                "breakdown_type": "event",
                "breakdown_limit": 3,
                "breakdown": ["some_breakdown_val"],
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            events_by_person = {}
            for num in range(5):
                for i in range(num):
                    person_id = f"person_{num}_{i}"
                    events_by_person[person_id] = [
                        {
                            "event": "sign up",
                            "timestamp": datetime(2020, 1, 1, 12),
                            "properties": {"some_breakdown_val": str(num)},
                        },
                        {
                            "event": "play movie",
                            "timestamp": datetime(2020, 1, 1, 13),
                            "properties": {"some_breakdown_val": str(num)},
                        },
                        {
                            "event": "buy",
                            "timestamp": datetime(2020, 1, 1, 15),
                            "properties": {"some_breakdown_val": str(num)},
                        },
                    ]

                    # no breakdown value for this guy
            events_by_person["person_null"] = [
                {"event": "sign up", "timestamp": datetime(2020, 1, 1, 12)},
                {"event": "play movie", "timestamp": datetime(2020, 1, 1, 13)},
                {"event": "buy", "timestamp": datetime(2020, 1, 1, 15)},
            ]
            people = journeys_for(events_by_person, self.team)

            result = funnel.run()

            breakdown_vals = sorted([res[0]["breakdown"] for res in result])
            self.assertEqual([["2"], ["3"], ["4"], ["Other"]], breakdown_vals)
            # skipped 1 and '' because the limit was 3.
            self.assertTrue(people["person_null"].uuid in self._get_actor_ids_at_step(filter, 1, "Other"))

        @also_test_with_materialized_columns(["some_breakdown_val"])
        def test_funnel_step_custom_breakdown_limit_with_nulls_included(self):
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
                "breakdown_type": "event",
                "breakdown_limit": 6,
                "breakdown": ["some_breakdown_val"],
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            events_by_person = {}
            for num in range(5):
                for i in range(num):
                    person_id = f"person_{num}_{i}"
                    events_by_person[person_id] = [
                        {
                            "event": "sign up",
                            "timestamp": datetime(2020, 1, 1, 12),
                            "properties": {"some_breakdown_val": str(num)},
                        },
                        {
                            "event": "play movie",
                            "timestamp": datetime(2020, 1, 1, 13),
                            "properties": {"some_breakdown_val": str(num)},
                        },
                        {
                            "event": "buy",
                            "timestamp": datetime(2020, 1, 1, 15),
                            "properties": {"some_breakdown_val": str(num)},
                        },
                    ]

                    # no breakdown value for this guy
            events_by_person["person_null"] = [
                {"event": "sign up", "timestamp": datetime(2020, 1, 1, 12)},
                {"event": "play movie", "timestamp": datetime(2020, 1, 1, 13)},
                {"event": "buy", "timestamp": datetime(2020, 1, 1, 15)},
            ]
            people = journeys_for(events_by_person, self.team)

            result = funnel.run()

            breakdown_vals = sorted([res[0]["breakdown"] for res in result])
            self.assertEqual([[""], ["1"], ["2"], ["3"], ["4"]], breakdown_vals)
            # included 1 and '' because the limit was 6.

            for i in range(1, 5):
                self.assertEqual(len(self._get_actor_ids_at_step(filter, 3, str(i))), i)

            self.assertEqual([people["person_null"].uuid], self._get_actor_ids_at_step(filter, 1, ""))
            self.assertEqual([people["person_null"].uuid], self._get_actor_ids_at_step(filter, 3, ""))

        @also_test_with_materialized_columns(["$browser"])
        def test_funnel_step_breakdown_event_single_person_multiple_breakdowns(self):
            filters = {
                "events": [{"id": "sign up", "order": 0}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": ["$browser"],
                "breakdown_attribution_type": "step",
                "breakdown_attribution_value": "0",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            events_by_person = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome"},
                    },
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 13),
                        "properties": {"$browser": "Safari"},
                    },
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Mac"},
                    },
                    # mixed property type!
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 15),
                        "properties": {"$browser": 0},
                    },
                ]
            }
            people = journeys_for(events_by_person, self.team)

            result = funnel.run()
            result = sorted(result, key=lambda res: res[0]["breakdown"])

            self._assert_funnel_breakdown_result_is_correct(
                result[0], [FunnelStepResult(name="sign up", breakdown=["0"], count=1)]
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "0"), [people["person1"].uuid])

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [FunnelStepResult(name="sign up", count=1, breakdown=["Chrome"])],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Chrome"),
                [people["person1"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[2],
                [FunnelStepResult(name="sign up", count=1, breakdown=["Mac"])],
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "Mac"), [people["person1"].uuid])

            self._assert_funnel_breakdown_result_is_correct(
                result[3],
                [FunnelStepResult(name="sign up", count=1, breakdown=["Safari"])],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Safari"),
                [people["person1"].uuid],
            )

        def test_funnel_step_breakdown_event_single_person_events_with_multiple_properties(self):
            filters = {
                "events": [
                    {"id": "sign up", "order": 0},
                    {"id": "play movie", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": ["$browser"],
                "breakdown_attribution_type": "all_events",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            people = journeys_for(
                {
                    "person1": [
                        {
                            "event": "sign up",
                            "timestamp": datetime(2020, 1, 1, 12),
                            "properties": {"$browser": "Chrome"},
                        },
                        {
                            "event": "play movie",
                            "timestamp": datetime(2020, 1, 2, 12, 30),
                            "properties": {"$browser": "Safari"},
                        },
                        {
                            "event": "sign up",
                            "timestamp": datetime(2020, 1, 2, 13),
                            "properties": {"$browser": "Safari"},
                        },
                        {
                            "event": "play movie",
                            "timestamp": datetime(2020, 1, 2, 14),
                            "properties": {"$browser": "Safari"},
                        },
                    ]
                },
                self.team,
            )
            result = funnel.run()

            self.assertEqual(len(result), 2)

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Chrome"]),
                    FunnelStepResult(name="play movie", count=0, breakdown=["Chrome"]),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Chrome"),
                [people["person1"].uuid],
            )
            self.assertCountEqual(self._get_actor_ids_at_step(filter, 2, "Chrome"), [])

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Safari"]),
                    FunnelStepResult(
                        name="play movie",
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                        breakdown=["Safari"],
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Safari"),
                [people["person1"].uuid],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 2, "Safari"),
                [people["person1"].uuid],
            )

        @also_test_with_materialized_columns(person_properties=["key"], verify_no_jsonextract=False)
        def test_funnel_cohort_breakdown(self):
            # This caused some issues with SQL parsing
            _create_person(
                distinct_ids=[f"person1"],
                team_id=self.team.pk,
                properties={"key": "value"},
            )
            people = journeys_for(
                {"person1": [{"event": "sign up", "timestamp": datetime(2020, 1, 2, 12)}]},
                self.team,
                create_people=False,
            )

            cohort = Cohort.objects.create(
                team=self.team,
                name="test_cohort",
                groups=[{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
            )
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
                "breakdown": ["all", cohort.pk],
                "breakdown_attribution_type": "step",
                "breakdown_attribution_value": 0,
                # first touch means same user can't be in 'all' and the other cohort both
            }
            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            result = funnel.run()
            self.assertEqual(len(result[0]), 3)
            self.assertEqual(result[0][0]["breakdown"], "all users")
            self.assertEqual(len(result[1]), 3)
            self.assertEqual(result[1][0]["breakdown"], "test_cohort")
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, cohort.pk),
                [people["person1"].uuid],
            )
            self.assertCountEqual(self._get_actor_ids_at_step(filter, 2, cohort.pk), [])

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, ALL_USERS_COHORT_ID),
                [people["person1"].uuid],
            )
            self.assertCountEqual(self._get_actor_ids_at_step(filter, 2, ALL_USERS_COHORT_ID), [])

            # non array
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
                "breakdown": cohort.pk,
            }
            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            result = funnel.run()
            self.assertEqual(len(result[0]), 3)
            self.assertEqual(result[0][0]["breakdown"], "test_cohort")
            self.assertEqual(result[0][0]["breakdown_value"], cohort.pk)
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, cohort.pk),
                [people["person1"].uuid],
            )
            self.assertCountEqual(self._get_actor_ids_at_step(filter, 2, cohort.pk), [])

        def test_basic_funnel_default_funnel_days_breakdown_event(self):
            events_by_person = {
                "user_1": [
                    {
                        "event": "user signed up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$current_url": "https://posthog.com/docs/x"},
                    },
                    {
                        "event": "paid",
                        "timestamp": datetime(2020, 1, 10, 14),
                        "properties": {"$current_url": "https://posthog.com/docs/x"},
                    },
                ]
            }
            # Dummy events to make sure that breakdown is not confused
            # It was confused before due to the nature of fetching breakdown values with a LIMIT based on value popularity
            # See https://github.com/PostHog/posthog/pull/5496
            for current_url_letter in ascii_lowercase[:20]:
                # Twenty dummy breakdown values
                for _ in range(2):
                    # Each twice, so that the breakdown values from dummy events rank higher in raw order
                    # This test makes sure that events are prefiltered properly to avoid problems with this raw order
                    events_by_person["user_1"].append(
                        {
                            "event": "user signed up",
                            "timestamp": datetime(2020, 1, 2, 14),
                            "properties": {"$current_url": f"https://posthog.com/blog/{current_url_letter}"},
                        }
                    )

            journeys_for(events_by_person, self.team)

            filters = {
                "events": [
                    {
                        "id": "user signed up",
                        "type": "events",
                        "order": 0,
                        "properties": [
                            {
                                "key": "$current_url",
                                "operator": "icontains",
                                "type": "event",
                                "value": "https://posthog.com/docs",
                            }
                        ],
                    },
                    {"id": "paid", "type": "events", "order": 1},
                ],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-14",
                "breakdown": ["$current_url"],
                "breakdown_type": "event",
            }

            result = Funnel(Filter(data=filters), self.team).run()

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(
                        name="user signed up",
                        count=1,
                        breakdown=["https://posthog.com/docs/x"],
                    ),
                    FunnelStepResult(
                        name="paid",
                        count=1,
                        average_conversion_time=691200.0,
                        median_conversion_time=691200.0,
                        breakdown=["https://posthog.com/docs/x"],
                    ),
                ],
            )

        @also_test_with_materialized_columns(["$current_url"])
        def test_basic_funnel_default_funnel_days_breakdown_action(self):
            # Same case as test_basic_funnel_default_funnel_days_breakdown_event but with an action
            user_signed_up_action = _create_action(name="user signed up", event="user signed up", team=self.team)

            events_by_person = {
                "user_1": [
                    {
                        "event": "user signed up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$current_url": "https://posthog.com/docs/x"},
                    },
                    {
                        "event": "paid",
                        "timestamp": datetime(2020, 1, 10, 14),
                        "properties": {"$current_url": "https://posthog.com/docs/x"},
                    },
                ]
            }
            for current_url_letter in ascii_lowercase[:20]:
                for _ in range(2):
                    events_by_person["user_1"].append(
                        {
                            "event": "user signed up",
                            "timestamp": datetime(2020, 1, 2, 14),
                            "properties": {"$current_url": f"https://posthog.com/blog/{current_url_letter}"},
                        }
                    )

            journeys_for(events_by_person, self.team)

            filters = {
                "actions": [
                    {
                        "id": user_signed_up_action.id,
                        "order": 0,
                        "properties": [
                            {
                                "key": "$current_url",
                                "operator": "icontains",
                                "type": "event",
                                "value": "https://posthog.com/docs",
                            }
                        ],
                    }
                ],
                "events": [{"id": "paid", "type": "events", "order": 1}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-14",
                "breakdown": ["$current_url"],
                "breakdown_type": "event",
            }

            result = Funnel(Filter(data=filters), self.team).run()

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(
                        name="user signed up",
                        count=1,
                        breakdown=["https://posthog.com/docs/x"],
                        type="actions",
                        action_id=user_signed_up_action.id,
                    ),
                    FunnelStepResult(
                        name="paid",
                        count=1,
                        average_conversion_time=691200.0,
                        median_conversion_time=691200.0,
                        breakdown=["https://posthog.com/docs/x"],
                    ),
                ],
            )

        def test_funnel_step_breakdown_with_first_touch_attribution(self):
            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "buy", "order": 1}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": ["$browser"],
                "breakdown_attribution_type": "first_touch",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            events_by_person = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome"},
                    },
                    {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
                ],
                "person2": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 13),
                        "properties": {"$browser": "Safari"},
                    },
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Mac"},
                    },
                    {"event": "buy", "timestamp": datetime(2020, 1, 2, 15)},
                ],
                "person4": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 15),
                        "properties": {"$browser": 0},
                    },
                    # first touch means alakazam is disregarded
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 16),
                        "properties": {"$browser": "alakazam"},
                    },
                ],
                # no properties dude, represented by ''
                "person5": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 2, 15)},
                    {"event": "buy", "timestamp": datetime(2020, 1, 2, 16)},
                ],
            }
            people = journeys_for(events_by_person, self.team)

            result = funnel.run()
            result = sorted(result, key=lambda res: res[0]["breakdown"])

            self.assertEqual(len(result), 5)

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown=[""], count=1),
                    FunnelStepResult(
                        name="buy",
                        breakdown=[""],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, ""), [people["person5"].uuid])

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", breakdown=["0"], count=1),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["0"],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "0"), [people["person4"].uuid])

            self._assert_funnel_breakdown_result_is_correct(
                result[2],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Chrome"]),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Chrome"],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Chrome"),
                [people["person1"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[3],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Mac"]),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Mac"],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "Mac"), [people["person3"].uuid])

            self._assert_funnel_breakdown_result_is_correct(
                result[4],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Safari"]),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Safari"],
                        count=1,
                        average_conversion_time=86400,
                        median_conversion_time=86400,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Safari"),
                [people["person2"].uuid],
            )

        def test_funnel_step_breakdown_with_last_touch_attribution(self):
            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "buy", "order": 1}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": ["$browser"],
                "breakdown_attribution_type": "last_touch",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            events_by_person = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome"},
                    },
                    {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
                ],
                "person2": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 13),
                        "properties": {"$browser": "Safari"},
                    },
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Mac"},
                    },
                    {"event": "buy", "timestamp": datetime(2020, 1, 2, 15)},
                ],
                "person4": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 15),
                        "properties": {"$browser": 0},
                    },
                    # last touch means 0 is disregarded
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 16),
                        "properties": {"$browser": "Alakazam"},
                    },
                ],
                # no properties dude, represented by ''
                "person5": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 2, 15)},
                    {"event": "buy", "timestamp": datetime(2020, 1, 2, 16)},
                ],
            }
            people = journeys_for(events_by_person, self.team)

            result = funnel.run()
            result = sorted(result, key=lambda res: res[0]["breakdown"])

            self.assertEqual(len(result), 5)

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown=[""], count=1),
                    FunnelStepResult(
                        name="buy",
                        breakdown=[""],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, ""), [people["person5"].uuid])

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", breakdown=["Alakazam"], count=1),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Alakazam"],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Alakazam"),
                [people["person4"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[2],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Chrome"]),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Chrome"],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Chrome"),
                [people["person1"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[3],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Mac"]),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Mac"],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "Mac"), [people["person3"].uuid])

            self._assert_funnel_breakdown_result_is_correct(
                result[4],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Safari"]),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Safari"],
                        count=1,
                        average_conversion_time=86400,
                        median_conversion_time=86400,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Safari"),
                [people["person2"].uuid],
            )

        def test_funnel_step_breakdown_with_step_attribution(self):
            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "buy", "order": 1}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": ["$browser"],
                "breakdown_attribution_type": "step",
                "breakdown_attribution_value": "0",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            events_by_person = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome"},
                    },
                    {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
                ],
                "person2": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 13),
                        "properties": {"$browser": "Safari"},
                    },
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Mac"},
                    },
                    {"event": "buy", "timestamp": datetime(2020, 1, 2, 15)},
                ],
                "person4": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 15),
                        "properties": {"$browser": 0},
                    },
                    # step attribution means alakazam is valid when step = 1
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 16),
                        "properties": {"$browser": "alakazam"},
                    },
                ],
            }
            people = journeys_for(events_by_person, self.team)

            result = funnel.run()
            result = sorted(result, key=lambda res: res[0]["breakdown"])

            self.assertEqual(len(result), 4)

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown=[""], count=1),
                    FunnelStepResult(
                        name="buy",
                        breakdown=[""],
                        count=1,
                        average_conversion_time=86400,
                        median_conversion_time=86400,
                    ),
                ],
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, ""), [people["person2"].uuid])

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", breakdown=["0"], count=1),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["0"],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "0"), [people["person4"].uuid])

            self._assert_funnel_breakdown_result_is_correct(
                result[2],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Chrome"]),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Chrome"],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Chrome"),
                [people["person1"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[3],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Mac"]),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Mac"],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, "Mac"), [people["person3"].uuid])

        def test_funnel_step_breakdown_with_step_one_attribution(self):
            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "buy", "order": 1}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": ["$browser"],
                "breakdown_attribution_type": "step",
                "breakdown_attribution_value": "1",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            events_by_person = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome"},
                    },
                    {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
                ],
                "person2": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 13),
                        "properties": {"$browser": "Safari"},
                    },
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Mac"},
                    },
                    {"event": "buy", "timestamp": datetime(2020, 1, 2, 15)},
                ],
                "person4": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 15),
                        "properties": {"$browser": 0},
                    },
                    # step attribution means alakazam is valid when step = 1
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 16),
                        "properties": {"$browser": "alakazam"},
                    },
                ],
            }
            people = journeys_for(events_by_person, self.team)

            result = funnel.run()
            result = sorted(result, key=lambda res: res[0]["breakdown"])

            self.assertEqual(len(result), 3)
            # Chrome and Mac goes away, Safari comes back

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown=[""], count=2),
                    FunnelStepResult(
                        name="buy",
                        breakdown=[""],
                        count=2,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, ""),
                [people["person1"].uuid, people["person3"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Safari"]),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Safari"],
                        count=1,
                        average_conversion_time=86400,
                        median_conversion_time=86400,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "Safari"),
                [people["person2"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[2],
                [
                    FunnelStepResult(name="sign up", breakdown=["alakazam"], count=1),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["alakazam"],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "alakazam"),
                [people["person4"].uuid],
            )

        def test_funnel_step_multiple_breakdown_with_first_touch_attribution(self):
            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "buy", "order": 1}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": ["$browser", "$version"],
                "breakdown_attribution_type": "first_touch",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            events_by_person = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome", "$version": "xyz"},
                    },
                    {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
                ],
                "person2": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 13),
                        "properties": {"$browser": "Safari", "$version": "xyz"},
                    },
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Mac"},
                    },
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 15),
                        "properties": {"$version": "no-mac"},
                    },
                ],
                "person4": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 15),
                        "properties": {"$browser": 0, "$version": 0},
                    },
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 16),
                        "properties": {"$browser": "alakazam"},
                    },
                ],
                # no properties dude, represented by ''
                "person5": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 2, 15)},
                    {"event": "buy", "timestamp": datetime(2020, 1, 2, 16)},
                ],
            }
            people = journeys_for(events_by_person, self.team)

            result = funnel.run()
            result = sorted(result, key=lambda res: res[0]["breakdown"])

            self.assertEqual(len(result), 5)

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown=["", ""], count=1),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["", ""],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, ["", ""]),
                [people["person5"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", breakdown=["0", "0"], count=1),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["0", "0"],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, ["0", "0"]),
                [people["person4"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[2],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Chrome", "xyz"]),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Chrome", "xyz"],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, ["Chrome", "xyz"]),
                [people["person1"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[3],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Mac", ""]),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Mac", ""],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, ["Mac", ""]),
                [people["person3"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[4],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Safari", "xyz"]),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Safari", "xyz"],
                        count=1,
                        average_conversion_time=86400,
                        median_conversion_time=86400,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, ["Safari", "xyz"]),
                [people["person2"].uuid],
            )

        def test_funnel_step_multiple_breakdown_with_first_touch_attribution_incomplete_funnel(self):
            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "buy", "order": 1}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": ["$browser", "$version"],
                "breakdown_attribution_type": "first_touch",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            events_by_person = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome", "$version": "xyz"},
                    },
                    {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
                ],
                "person2": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 13),
                        "properties": {"$browser": "Safari", "$version": "xyz"},
                    },
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Mac"},
                    },
                    # {"event": "buy", "timestamp": datetime(2020, 1, 2, 15), "properties": {"$version": "no-mac"}},
                ],
                "person4": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 15),
                        "properties": {"$browser": 0, "$version": 0},
                    },
                    # {"event": "buy", "timestamp": datetime(2020, 1, 2, 16), "properties": {"$browser": "alakazam"}},
                ],
                # no properties dude, represented by ''
                "person5": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 2, 15)},
                    {"event": "buy", "timestamp": datetime(2020, 1, 2, 16)},
                ],
            }
            people = journeys_for(events_by_person, self.team)

            result = funnel.run()
            result = sorted(result, key=lambda res: res[0]["breakdown"])

            self.assertEqual(len(result), 5)

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown=["", ""], count=1),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["", ""],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, ["", ""]),
                [people["person5"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", breakdown=["0", "0"], count=1),
                    FunnelStepResult(name="buy", breakdown=["0", "0"], count=0),
                ],
            )
            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, ["0", "0"]),
                [people["person4"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[2],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Chrome", "xyz"]),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Chrome", "xyz"],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, ["Chrome", "xyz"]),
                [people["person1"].uuid],
            )

            self._assert_funnel_breakdown_result_is_correct(
                result[3],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Mac", ""]),
                    FunnelStepResult(name="buy", breakdown=["Mac", ""], count=0),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, ["Mac", ""]),
                [people["person3"].uuid],
            )
            self.assertCountEqual(self._get_actor_ids_at_step(filter, 2, ["Mac", ""]), [])

            self._assert_funnel_breakdown_result_is_correct(
                result[4],
                [
                    FunnelStepResult(name="sign up", count=1, breakdown=["Safari", "xyz"]),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["Safari", "xyz"],
                        count=1,
                        average_conversion_time=86400,
                        median_conversion_time=86400,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, ["Safari", "xyz"]),
                [people["person2"].uuid],
            )

        def test_funnel_step_breakdown_with_step_one_attribution_incomplete_funnel(self):
            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "buy", "order": 1}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": ["$browser"],
                "breakdown_attribution_type": "step",
                "breakdown_attribution_value": "1",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            events_by_person = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome"},
                    },
                    {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
                ],
                "person2": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                    # {"event": "buy", "timestamp": datetime(2020, 1, 2, 13), "properties": {"$browser": "Safari"}}
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Mac"},
                    },
                    # {"event": "buy", "timestamp": datetime(2020, 1, 2, 15)}
                ],
                "person4": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 15),
                        "properties": {"$browser": 0},
                    },
                    # step attribution means alakazam is valid when step = 1
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 16),
                        "properties": {"$browser": "alakazam"},
                    },
                ],
            }
            people = journeys_for(events_by_person, self.team)

            result = funnel.run()
            result = sorted(result, key=lambda res: res[0]["breakdown"])

            # Breakdown by step_1 means funnel items that never reach step_1 are NULLed out
            self.assertEqual(len(result), 2)
            # Chrome and Mac and Safari goes away

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown=[""], count=1),
                    FunnelStepResult(
                        name="buy",
                        breakdown=[""],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, ""), [people["person1"].uuid])

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", breakdown=["alakazam"], count=1),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["alakazam"],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "alakazam"),
                [people["person4"].uuid],
            )

        def test_funnel_step_non_array_breakdown_with_step_one_attribution_incomplete_funnel(self):
            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "buy", "order": 1}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": "$browser",
                "breakdown_attribution_type": "step",
                "breakdown_attribution_value": "1",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            events_by_person = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome"},
                    },
                    {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
                ],
                "person2": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                    # {"event": "buy", "timestamp": datetime(2020, 1, 2, 13), "properties": {"$browser": "Safari"}}
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Mac"},
                    },
                    # {"event": "buy", "timestamp": datetime(2020, 1, 2, 15)}
                ],
                "person4": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 15),
                        "properties": {"$browser": 0},
                    },
                    # step attribution means alakazam is valid when step = 1
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 16),
                        "properties": {"$browser": "alakazam"},
                    },
                ],
            }
            people = journeys_for(events_by_person, self.team)

            result = funnel.run()
            result = sorted(result, key=lambda res: res[0]["breakdown"])

            # Breakdown by step_1 means funnel items that never reach step_1 are NULLed out
            self.assertEqual(len(result), 2)
            # Chrome and Mac and Safari goes away

            self._assert_funnel_breakdown_result_is_correct(
                result[0],
                [
                    FunnelStepResult(name="sign up", breakdown=[""], count=1),
                    FunnelStepResult(
                        name="buy",
                        breakdown=[""],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(self._get_actor_ids_at_step(filter, 1, ""), [people["person1"].uuid])

            self._assert_funnel_breakdown_result_is_correct(
                result[1],
                [
                    FunnelStepResult(name="sign up", breakdown=["alakazam"], count=1),
                    FunnelStepResult(
                        name="buy",
                        breakdown=["alakazam"],
                        count=1,
                        average_conversion_time=3600,
                        median_conversion_time=3600,
                    ),
                ],
            )

            self.assertCountEqual(
                self._get_actor_ids_at_step(filter, 1, "alakazam"),
                [people["person4"].uuid],
            )

        @snapshot_clickhouse_queries
        def test_funnel_step_multiple_breakdown_snapshot(self):
            # No person querying here, so snapshots are more legible

            filters = {
                "events": [{"id": "sign up", "order": 0}, {"id": "buy", "order": 1}],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": ["$browser", "$version"],
                "breakdown_attribution_type": "first_touch",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            events_by_person = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome", "$version": "xyz"},
                    },
                    {"event": "buy", "timestamp": datetime(2020, 1, 1, 13)},
                ],
                "person2": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 13),
                        "properties": {"$browser": "Safari", "$version": "xyz"},
                    },
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Mac"},
                    },
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 15),
                        "properties": {"$version": "no-mac"},
                    },
                ],
                "person4": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 15),
                        "properties": {"$browser": 0, "$version": 0},
                    },
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 16),
                        "properties": {"$browser": "alakazam"},
                    },
                ],
                # no properties dude, represented by ''
                "person5": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 2, 15)},
                    {"event": "buy", "timestamp": datetime(2020, 1, 2, 16)},
                ],
            }
            journeys_for(events_by_person, self.team)

            result = funnel.run()
            result = sorted(result, key=lambda res: res[0]["breakdown"])

            self.assertEqual(len(result), 5)

        @snapshot_clickhouse_queries
        def test_funnel_breakdown_correct_breakdown_props_are_chosen(self):
            # No person querying here, so snapshots are more legible

            filters = {
                "events": [
                    {"id": "sign up", "order": 0},
                    {
                        "id": "buy",
                        "properties": [{"type": "event", "key": "$version", "value": "xyz"}],
                        "order": 1,
                    },
                ],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": "$browser",
                "breakdown_attribution_type": "first_touch",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            events_by_person = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome", "$version": "xyz"},
                    },
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 1, 13),
                        "properties": {"$browser": "Chrome"},
                    },
                    # discarded at step 1 because doesn't meet criteria
                ],
                "person2": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 13),
                        "properties": {"$browser": "Safari", "$version": "xyz"},
                    },
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Mac"},
                    },
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 15),
                        "properties": {"$version": "xyz", "$browser": "Mac"},
                    },
                ],
                # no properties dude, represented by '', who finished step 0
                "person5": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 2, 15)},
                    {"event": "buy", "timestamp": datetime(2020, 1, 2, 16)},
                ],
            }
            journeys_for(events_by_person, self.team)

            result = funnel.run()
            result = sorted(result, key=lambda res: res[0]["breakdown"])

            self.assertEqual(len(result), 4)

            self.assertCountEqual(
                [res[0]["breakdown"] for res in result],
                [["Mac"], ["Chrome"], ["Safari"], [""]],
            )

        @snapshot_clickhouse_queries
        def test_funnel_breakdown_correct_breakdown_props_are_chosen_for_step(self):
            # No person querying here, so snapshots are more legible

            filters = {
                "events": [
                    {"id": "sign up", "order": 0},
                    {
                        "id": "buy",
                        "properties": [{"type": "event", "key": "$version", "value": "xyz"}],
                        "order": 1,
                    },
                ],
                "insight": INSIGHT_FUNNELS,
                "date_from": "2020-01-01",
                "date_to": "2020-01-08",
                "funnel_window_days": 7,
                "breakdown_type": "event",
                "breakdown": "$browser",
                "breakdown_attribution_type": "step",
                "breakdown_attribution_value": "1",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)

            # event
            events_by_person = {
                "person1": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 1, 12),
                        "properties": {"$browser": "Chrome", "$version": "xyz"},
                    },
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 1, 13),
                        "properties": {"$browser": "Chrome"},
                    },
                    # discarded because doesn't meet criteria
                ],
                "person2": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 1, 13)},
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 13),
                        "properties": {"$browser": "Safari", "$version": "xyz"},
                    },
                ],
                "person3": [
                    {
                        "event": "sign up",
                        "timestamp": datetime(2020, 1, 2, 14),
                        "properties": {"$browser": "Mac"},
                    },
                    {
                        "event": "buy",
                        "timestamp": datetime(2020, 1, 2, 15),
                        "properties": {"$version": "xyz", "$browser": "Mac"},
                    },
                ],
                # no properties dude, doesn't make it to step 1, and since breakdown on step 1, is discarded completely
                "person5": [
                    {"event": "sign up", "timestamp": datetime(2020, 1, 2, 15)},
                    {"event": "buy", "timestamp": datetime(2020, 1, 2, 16)},
                ],
            }
            journeys_for(events_by_person, self.team)

            result = funnel.run()
            result = sorted(result, key=lambda res: res[0]["breakdown"])

            self.assertEqual(len(result), 2)

            self.assertCountEqual([res[0]["breakdown"] for res in result], [["Mac"], ["Safari"]])

        def test_funnel_personless_events_are_supported_with_breakdown(self):
            personless_user = uuid.uuid4()
            _create_event(
                event="user signed up",
                distinct_id=personless_user,
                person_id=personless_user,
                properties={"cohort": "A"},
                team=self.team,
            )
            _create_event(
                event="added to cart",
                distinct_id=personless_user,
                person_id=personless_user,
                properties={"cohort": "A"},
                team=self.team,
            )

            filters = {
                "events": [
                    {
                        "type": "events",
                        "id": "user signed up",
                        "order": 0,
                        "name": "user signed up",
                        "math": "total",
                    },
                    {
                        "type": "events",
                        "id": "added to cart",
                        "order": 1,
                        "name": "added to cart",
                        "math": "total",
                    },
                ],
                "funnel_window_days": 14,
                "breakdown_value": ["cohort"],
                "breakdown": "event",
            }

            filter = Filter(data=filters)
            funnel = Funnel(filter, self.team)
            result = funnel.run()
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0][0]["count"], 1)
            self.assertEqual(result[0][1]["count"], 1)

    return TestFunnelBreakdown


def sort_breakdown_funnel_results(results: list[dict[int, Any]]):
    return sorted(results, key=lambda r: r[0]["breakdown_value"])


def assert_funnel_results_equal(left: list[dict[str, Any]], right: list[dict[str, Any]]):
    """
    Helper to be able to compare two funnel results, but exclude people urls
    from the comparison, as these include:

        1. all the params from the request, and will thus almost always be
        different for varying inputs
        2. contain timestamps which are not stable across runs
    """

    def _filter(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**step, "converted_people_url": None, "dropped_people_url": None} for step in steps]

    assert len(left) == len(right)

    for index, item in enumerate(_filter(left)):
        other = _filter(right)[index]
        assert item.keys() == other.keys()
        for key in item.keys():
            try:
                assert item[key] == other[key]
            except AssertionError as e:
                e.args += (
                    f"failed comparing ${key}",
                    f'Got "{item[key]}" and "{other[key]}"',
                )
                raise
