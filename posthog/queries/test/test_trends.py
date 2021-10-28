import json
from typing import List, Tuple

from freezegun import freeze_time

from posthog.constants import (
    ENTITY_ID,
    ENTITY_TYPE,
    TREND_FILTER_TYPE_EVENTS,
    TRENDS_BAR_VALUE,
    TRENDS_LIFECYCLE,
    TRENDS_TABLE,
)
from posthog.models import (
    Action,
    ActionStep,
    Cohort,
    Entity,
    Event,
    Filter,
    Organization,
    Person,
)
from posthog.queries.abstract_test.test_interval import AbstractIntervalTest
from posthog.queries.abstract_test.test_timerange import AbstractTimerangeTest
from posthog.queries.trends import Trends, breakdown_label
from posthog.tasks.calculate_action import calculate_action, calculate_actions_from_last_calculation
from posthog.test.base import APIBaseTest, test_with_materialized_columns
from posthog.utils import generate_cache_key, relative_date_parse


# parameterize tests to reuse in EE
def trend_test_factory(trends, event_factory, person_factory, action_factory, cohort_factory):
    class TestTrends(AbstractTimerangeTest, AbstractIntervalTest, APIBaseTest):
        maxDiff = None

        def _get_trend_people(self, filter: Filter, entity: Entity):
            data = filter.to_dict()
            if data.get("events", None):
                data.update({"events": json.dumps(data["events"])})
            response = self.client.get(
                f"/api/projects/{self.team.id}/actions/people/",
                data={**data, ENTITY_TYPE: entity.type, ENTITY_ID: entity.id,},
            ).json()
            return response["results"][0]["people"]

        def _create_events(self, use_time=False) -> Tuple[Action, Person]:

            person = person_factory(
                team_id=self.team.pk, distinct_ids=["blabla", "anonymous_id"], properties={"$some_prop": "some_val"}
            )
            _, _, secondTeam = Organization.objects.bootstrap(None, team_fields={"api_token": "token456"})

            freeze_without_time = ["2019-12-24", "2020-01-01", "2020-01-02"]
            freeze_with_time = [
                "2019-12-24 03:45:34",
                "2020-01-01 00:06:34",
                "2020-01-02 16:34:34",
            ]

            freeze_args = freeze_without_time
            if use_time:
                freeze_args = freeze_with_time

            with freeze_time(freeze_args[0]):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$bool_prop": True},
                )

            with freeze_time(freeze_args[1]):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$bool_prop": False},
                )
                event_factory(
                    team=self.team, event="sign up", distinct_id="anonymous_id", properties={"$bool_prop": False}
                )
                event_factory(team=self.team, event="sign up", distinct_id="blabla")
            with freeze_time(freeze_args[2]):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "other_value", "$some_numerical_prop": 80,},
                )
                event_factory(team=self.team, event="no events", distinct_id="blabla")

                # second team should have no effect
                event_factory(
                    team=secondTeam,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "other_value"},
                )

            no_events = action_factory(team=self.team, name="no events")
            sign_up_action = action_factory(team=self.team, name="sign up")

            calculate_actions_from_last_calculation()

            return sign_up_action, person

        def _create_breakdown_events(self):
            freeze_without_time = ["2020-01-02"]

            with freeze_time(freeze_without_time[0]):
                for i in range(25):
                    event_factory(
                        team=self.team, event="sign up", distinct_id="blabla", properties={"$some_property": i},
                    )
            sign_up_action = action_factory(team=self.team, name="sign up")

        def assertEntityResponseEqual(self, response1, response2, remove=("action", "label")):
            if len(response1):
                for attr in remove:
                    response1[0].pop(attr)
            else:
                return False
            if len(response2):
                for attr in remove:
                    response2[0].pop(attr)
            else:
                return False
            self.assertDictEqual(response1[0], response2[0])

        def test_trends_per_day(self):
            self._create_events()
            with freeze_time("2020-01-04T13:00:01Z"):
                # with self.assertNumQueries(16):
                response = trends().run(
                    Filter(data={"date_from": "-7d", "events": [{"id": "sign up"}, {"id": "no events"}],}), self.team,
                )
            self.assertEqual(response[0]["label"], "sign up")
            self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
            self.assertEqual(response[0]["data"][4], 3.0)
            self.assertEqual(response[0]["labels"][5], "2-Jan-2020")
            self.assertEqual(response[0]["data"][5], 1.0)

        # just make sure this doesn't error
        def test_no_props(self):
            with freeze_time("2020-01-04T13:01:01Z"):
                event_response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "$some_property",
                            "events": [
                                {"id": "sign up", "name": "sign up", "type": "events", "order": 0,},
                                {"id": "no events"},
                            ],
                        }
                    ),
                    self.team,
                )

        def test_trends_per_day_48hours(self):
            self._create_events()
            with freeze_time("2020-01-03T13:00:01Z"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-48h",
                            "interval": "day",
                            "events": [{"id": "sign up"}, {"id": "no events"}],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["data"][1], 1.0)
            self.assertEqual(response[0]["labels"][1], "2-Jan-2020")

        def test_trends_per_day_cumulative(self):
            self._create_events()
            with freeze_time("2020-01-04T13:00:01Z"):

                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-7d",
                            "display": "ActionsLineGraphCumulative",
                            "events": [{"id": "sign up"}],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["label"], "sign up")
            self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
            self.assertEqual(response[0]["data"][4], 3.0)
            self.assertEqual(response[0]["labels"][5], "2-Jan-2020")
            self.assertEqual(response[0]["data"][5], 4.0)

        def test_trends_single_aggregate_dau(self):
            self._create_events()
            with freeze_time("2020-01-04T13:00:01Z"):
                daily_response = trends().run(
                    Filter(
                        data={
                            "display": TRENDS_TABLE,
                            "interval": "week",
                            "events": [{"id": "sign up", "math": "dau"}],
                        }
                    ),
                    self.team,
                )

            with freeze_time("2020-01-04T13:00:01Z"):
                weekly_response = trends().run(
                    Filter(
                        data={"display": TRENDS_TABLE, "interval": "day", "events": [{"id": "sign up", "math": "dau"}],}
                    ),
                    self.team,
                )

            self.assertEqual(daily_response[0]["aggregated_value"], 1)
            self.assertEqual(daily_response[0]["aggregated_value"], weekly_response[0]["aggregated_value"])

        @test_with_materialized_columns(["$math_prop"])
        def test_trends_single_aggregate_math(self):
            person = person_factory(
                team_id=self.team.pk, distinct_ids=["blabla", "anonymous_id"], properties={"$some_prop": "some_val"}
            )
            with freeze_time("2020-01-01 00:06:34"):
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 1},
                )
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 1},
                )
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 1},
                )
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 2},
                )
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 3},
                )

            with freeze_time("2020-01-02 00:06:34"):
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 4},
                )
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$math_prop": 4},
                )

            with freeze_time("2020-01-04T13:00:01Z"):
                daily_response = trends().run(
                    Filter(
                        data={
                            "display": TRENDS_TABLE,
                            "interval": "week",
                            "events": [{"id": "sign up", "math": "median", "math_property": "$math_prop"}],
                        }
                    ),
                    self.team,
                )

            with freeze_time("2020-01-04T13:00:01Z"):
                weekly_response = trends().run(
                    Filter(
                        data={
                            "display": TRENDS_TABLE,
                            "interval": "day",
                            "events": [{"id": "sign up", "math": "median", "math_property": "$math_prop"}],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(daily_response[0]["aggregated_value"], 2.0)
            self.assertEqual(daily_response[0]["aggregated_value"], weekly_response[0]["aggregated_value"])

        @test_with_materialized_columns(person_properties=["name"], verify_no_jsonextract=False)
        def test_trends_breakdown_single_aggregate_cohorts(self):
            person_1 = person_factory(team_id=self.team.pk, distinct_ids=["Jane"], properties={"name": "Jane"})
            person_2 = person_factory(team_id=self.team.pk, distinct_ids=["John"], properties={"name": "John"})
            person_3 = person_factory(team_id=self.team.pk, distinct_ids=["Jill"], properties={"name": "Jill"})
            cohort1 = cohort_factory(
                team=self.team,
                name="cohort1",
                groups=[{"properties": [{"key": "name", "value": "Jane", "type": "person"}]}],
            )
            cohort2 = cohort_factory(
                team=self.team,
                name="cohort2",
                groups=[{"properties": [{"key": "name", "value": "John", "type": "person"}]}],
            )
            cohort3 = cohort_factory(
                team=self.team,
                name="cohort3",
                groups=[{"properties": [{"key": "name", "value": "Jill", "type": "person"}]}],
            )
            with freeze_time("2020-01-01 00:06:34"):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="John",
                    properties={"$some_property": "value", "$browser": "Chrome"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="John",
                    properties={"$some_property": "value", "$browser": "Chrome"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="Jill",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="Jill",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="Jill",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )

            with freeze_time("2020-01-02 00:06:34"):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="Jane",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="Jane",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )
            with freeze_time("2020-01-04T13:00:01Z"):
                event_response = trends().run(
                    Filter(
                        data={
                            "display": TRENDS_TABLE,
                            "breakdown": json.dumps([cohort1.pk, cohort2.pk, cohort3.pk, "all"]),
                            "breakdown_type": "cohort",
                            "events": [{"id": "sign up"}],
                        }
                    ),
                    self.team,
                )

            for result in event_response:
                if result["label"] == "sign up - cohort1":
                    self.assertEqual(result["aggregated_value"], 2)
                elif result["label"] == "sign up - cohort2":
                    self.assertEqual(result["aggregated_value"], 2)
                elif result["label"] == "sign up - cohort3":
                    self.assertEqual(result["aggregated_value"], 3)
                else:
                    self.assertEqual(result["aggregated_value"], 7)

        def test_trends_breakdown_single_aggregate(self):
            person = person_factory(
                team_id=self.team.pk, distinct_ids=["blabla", "anonymous_id"], properties={"$some_prop": "some_val"}
            )
            with freeze_time("2020-01-01 00:06:34"):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$browser": "Chrome"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$browser": "Chrome"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )

            with freeze_time("2020-01-02 00:06:34"):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$browser": "Safari"},
                )

            with freeze_time("2020-01-04T13:00:01Z"):
                daily_response = trends().run(
                    Filter(data={"display": TRENDS_TABLE, "breakdown": "$browser", "events": [{"id": "sign up"}],}),
                    self.team,
                )

            for result in daily_response:
                if result["breakdown_value"] == "Chrome":
                    self.assertEqual(result["aggregated_value"], 2)
                else:
                    self.assertEqual(result["aggregated_value"], 5)

        def test_trends_breakdown_single_aggregate_math(self):
            person = person_factory(
                team_id=self.team.pk, distinct_ids=["blabla", "anonymous_id"], properties={"$some_prop": "some_val"}
            )
            with freeze_time("2020-01-01 00:06:34"):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$math_prop": 1},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$math_prop": 1},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$math_prop": 1},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$math_prop": 2},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$math_prop": 3},
                )

            with freeze_time("2020-01-02 00:06:34"):
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$math_prop": 4},
                )
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "value", "$math_prop": 4},
                )

            with freeze_time("2020-01-04T13:00:01Z"):
                daily_response = trends().run(
                    Filter(
                        data={
                            "display": TRENDS_TABLE,
                            "interval": "day",
                            "breakdown": "$some_property",
                            "events": [{"id": "sign up", "math": "median", "math_property": "$math_prop"}],
                        }
                    ),
                    self.team,
                )

            with freeze_time("2020-01-04T13:00:01Z"):
                weekly_response = trends().run(
                    Filter(
                        data={
                            "display": TRENDS_TABLE,
                            "interval": "week",
                            "breakdown": "$some_property",
                            "events": [{"id": "sign up", "math": "median", "math_property": "$math_prop"}],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(daily_response[0]["aggregated_value"], 2.0)
            self.assertEqual(daily_response[0]["aggregated_value"], weekly_response[0]["aggregated_value"])

        @test_with_materialized_columns(["$math_prop", "$some_property"])
        def test_trends_breakdown_with_math_func(self):

            with freeze_time("2020-01-01 00:06:34"):
                for i in range(20):
                    person = person_factory(team_id=self.team.pk, distinct_ids=[f"person{i}"])
                    event_factory(
                        team=self.team,
                        event="sign up",
                        distinct_id=f"person{i}",
                        properties={"$some_property": f"value_{i}", "$math_prop": 1},
                    )
                    event_factory(
                        team=self.team,
                        event="sign up",
                        distinct_id=f"person{i}",
                        properties={"$some_property": f"value_{i}", "$math_prop": 1},
                    )

                person = person_factory(team_id=self.team.pk, distinct_ids=[f"person21"])
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id=f"person21",
                    properties={"$some_property": "value_21", "$math_prop": 25},
                )

            with freeze_time("2020-01-04T13:00:01Z"):
                daily_response = trends().run(
                    Filter(
                        data={
                            "display": TRENDS_TABLE,
                            "interval": "day",
                            "breakdown": "$some_property",
                            "events": [{"id": "sign up", "math": "p90", "math_property": "$math_prop"}],
                        }
                    ),
                    self.team,
                )

            breakdown_vals = [val["breakdown_value"] for val in daily_response]
            self.assertTrue("value_21" in breakdown_vals)

        def test_trends_compare(self):
            self._create_events()
            with freeze_time("2020-01-04T13:00:01Z"):
                response = trends().run(Filter(data={"compare": "true", "events": [{"id": "sign up"}]}), self.team)

            self.assertEqual(response[0]["label"], "sign up - current")
            self.assertEqual(response[0]["labels"][4], "day 4")
            self.assertEqual(response[0]["data"][4], 3.0)
            self.assertEqual(response[0]["labels"][5], "day 5")
            self.assertEqual(response[0]["data"][5], 1.0)

            self.assertEqual(response[1]["label"], "sign up - previous")
            self.assertEqual(response[1]["labels"][4], "day 4")
            self.assertEqual(response[1]["data"][4], 1.0)
            self.assertEqual(response[1]["labels"][5], "day 5")
            self.assertEqual(response[1]["data"][5], 0.0)

            with freeze_time("2020-01-04T13:00:01Z"):
                no_compare_response = trends().run(
                    Filter(data={"compare": "false", "events": [{"id": "sign up"}]}), self.team
                )

            self.assertEqual(no_compare_response[0]["label"], "sign up")
            self.assertEqual(no_compare_response[0]["labels"][4], "1-Jan-2020")
            self.assertEqual(no_compare_response[0]["data"][4], 3.0)
            self.assertEqual(no_compare_response[0]["labels"][5], "2-Jan-2020")
            self.assertEqual(no_compare_response[0]["data"][5], 1.0)

        def _test_events_with_dates(self, dates: List[str], result, query_time=None, **filter_params):
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person_1"], properties={"name": "John"})
            for time in dates:
                with freeze_time(time):
                    event_factory(
                        event="event_name", team=self.team, distinct_id="person_1", properties={"$browser": "Safari"},
                    )

            if query_time:
                with freeze_time(query_time):
                    response = trends().run(
                        Filter(data={**filter_params, "events": [{"id": "event_name"}]}), self.team,
                    )
            else:
                response = trends().run(Filter(data={**filter_params, "events": [{"id": "event_name"}]}), self.team,)
            self.assertEqual(response, result)

        def test_minute_interval(self):
            self._test_events_with_dates(
                dates=["2020-11-01 10:20:00", "2020-11-01 10:22:00", "2020-11-01 10:25:00"],
                interval="minute",
                date_from="2020-11-01 10:20:00",
                date_to="2020-11-01 10:30:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 3.0,
                        "data": [1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                        "labels": [
                            "1-Nov-2020 10:20",
                            "1-Nov-2020 10:21",
                            "1-Nov-2020 10:22",
                            "1-Nov-2020 10:23",
                            "1-Nov-2020 10:24",
                            "1-Nov-2020 10:25",
                            "1-Nov-2020 10:26",
                            "1-Nov-2020 10:27",
                            "1-Nov-2020 10:28",
                            "1-Nov-2020 10:29",
                            "1-Nov-2020 10:30",
                        ],
                        "days": [
                            "2020-11-01 10:20:00",
                            "2020-11-01 10:21:00",
                            "2020-11-01 10:22:00",
                            "2020-11-01 10:23:00",
                            "2020-11-01 10:24:00",
                            "2020-11-01 10:25:00",
                            "2020-11-01 10:26:00",
                            "2020-11-01 10:27:00",
                            "2020-11-01 10:28:00",
                            "2020-11-01 10:29:00",
                            "2020-11-01 10:30:00",
                        ],
                    }
                ],
            )

        def test_hour_interval(self):
            self._test_events_with_dates(
                dates=["2020-11-01 13:00:00", "2020-11-01 13:20:00", "2020-11-01 17:00:00"],
                interval="hour",
                date_from="2020-11-01 12:00:00",
                date_to="2020-11-01 18:00:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 3.0,
                        "data": [0.0, 2.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                        "labels": [
                            "1-Nov-2020 12:00",
                            "1-Nov-2020 13:00",
                            "1-Nov-2020 14:00",
                            "1-Nov-2020 15:00",
                            "1-Nov-2020 16:00",
                            "1-Nov-2020 17:00",
                            "1-Nov-2020 18:00",
                        ],
                        "days": [
                            "2020-11-01 12:00:00",
                            "2020-11-01 13:00:00",
                            "2020-11-01 14:00:00",
                            "2020-11-01 15:00:00",
                            "2020-11-01 16:00:00",
                            "2020-11-01 17:00:00",
                            "2020-11-01 18:00:00",
                        ],
                    }
                ],
            )

        def test_day_interval(self):
            self._test_events_with_dates(
                dates=["2020-11-01", "2020-11-02", "2020-11-03", "2020-11-04"],
                interval="day",
                date_from="2020-11-01",
                date_to="2020-11-07",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 4.0,
                        "data": [1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0],
                        "labels": [
                            "1-Nov-2020",
                            "2-Nov-2020",
                            "3-Nov-2020",
                            "4-Nov-2020",
                            "5-Nov-2020",
                            "6-Nov-2020",
                            "7-Nov-2020",
                        ],
                        "days": [
                            "2020-11-01",
                            "2020-11-02",
                            "2020-11-03",
                            "2020-11-04",
                            "2020-11-05",
                            "2020-11-06",
                            "2020-11-07",
                        ],
                    }
                ],
            )

        def test_week_interval(self):
            self._test_events_with_dates(
                dates=["2020-11-01", "2020-11-10", "2020-11-11", "2020-11-18"],
                interval="week",
                date_from="2020-10-29",  # having date after sunday + no events caused an issue in CH
                date_to="2020-11-24",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 4.0,
                        "data": [0.0, 1.0, 2.0, 1.0, 0.0],
                        "labels": ["25-Oct-2020", "1-Nov-2020", "8-Nov-2020", "15-Nov-2020", "22-Nov-2020",],
                        "days": ["2020-10-25", "2020-11-01", "2020-11-08", "2020-11-15", "2020-11-22"],
                    }
                ],
            )

        def test_month_interval(self):
            self._test_events_with_dates(
                dates=["2020-07-10", "2020-07-30", "2020-10-18"],
                interval="month",
                date_from="2020-6-01",
                date_to="2020-11-24",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 3.0,
                        "data": [0.0, 2.0, 0.0, 0.0, 1.0, 0.0],
                        "labels": ["1-Jun-2020", "1-Jul-2020", "1-Aug-2020", "1-Sep-2020", "1-Oct-2020", "1-Nov-2020"],
                        "days": ["2020-06-01", "2020-07-01", "2020-08-01", "2020-09-01", "2020-10-01", "2020-11-01"],
                    }
                ],
            )

        def test_interval_rounding(self):
            self._test_events_with_dates(
                dates=["2020-11-01", "2020-11-10", "2020-11-11", "2020-11-18"],
                interval="week",
                date_from="2020-11-04",
                date_to="2020-11-24",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 4.0,
                        "data": [1.0, 2.0, 1.0, 0.0],
                        "labels": ["1-Nov-2020", "8-Nov-2020", "15-Nov-2020", "22-Nov-2020"],
                        "days": ["2020-11-01", "2020-11-08", "2020-11-15", "2020-11-22"],
                    }
                ],
            )

        def test_interval_rounding_monthly(self):
            self._test_events_with_dates(
                dates=["2020-06-2", "2020-07-30",],
                interval="month",
                date_from="2020-6-7",  #  should round down to 6-1
                date_to="2020-7-30",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 2.0,
                        "data": [1.0, 1.0,],
                        "labels": ["1-Jun-2020", "1-Jul-2020"],
                        "days": ["2020-06-01", "2020-07-01",],
                    }
                ],
            )

        def test_today_timerange(self):
            self._test_events_with_dates(
                dates=["2020-11-01 10:20:00", "2020-11-01 10:22:00", "2020-11-01 10:25:00"],
                date_from="dStart",
                query_time="2020-11-01 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 3,
                        "data": [3],
                        "labels": ["1-Nov-2020"],
                        "days": ["2020-11-01"],
                    }
                ],
            )

        def test_yesterday_timerange(self):
            self._test_events_with_dates(
                dates=["2020-11-01 05:20:00", "2020-11-01 10:22:00", "2020-11-01 10:25:00"],
                date_from="-1d",
                date_to="dStart",
                query_time="2020-11-02 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 3.0,
                        "data": [3.0, 0.0],
                        "labels": ["1-Nov-2020", "2-Nov-2020"],
                        "days": ["2020-11-01", "2020-11-02"],
                    }
                ],
            )

        def test_last24hours_timerange(self):
            self._test_events_with_dates(
                dates=["2020-11-01 05:20:00", "2020-11-01 10:22:00", "2020-11-01 10:25:00", "2020-11-02 08:25:00"],
                date_from="-24h",
                query_time="2020-11-02 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 3,
                        "data": [2, 1],
                        "labels": ["1-Nov-2020", "2-Nov-2020"],
                        "days": ["2020-11-01", "2020-11-02"],
                    }
                ],
            )

        def test_last48hours_timerange(self):
            self._test_events_with_dates(
                dates=["2020-11-01 05:20:00", "2020-11-01 10:22:00", "2020-11-01 10:25:00", "2020-11-02 08:25:00"],
                date_from="-48h",
                query_time="2020-11-02 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 4.0,
                        "data": [0.0, 3.0, 1.0],
                        "labels": ["31-Oct-2020", "1-Nov-2020", "2-Nov-2020"],
                        "days": ["2020-10-31", "2020-11-01", "2020-11-02"],
                    }
                ],
            )

        def test_last7days_timerange(self):
            self._test_events_with_dates(
                dates=["2020-11-01 05:20:00", "2020-11-02 10:22:00", "2020-11-04 10:25:00", "2020-11-05 08:25:00"],
                date_from="-7d",
                query_time="2020-11-07 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 4.0,
                        "data": [0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0],
                        "labels": [
                            "31-Oct-2020",
                            "1-Nov-2020",
                            "2-Nov-2020",
                            "3-Nov-2020",
                            "4-Nov-2020",
                            "5-Nov-2020",
                            "6-Nov-2020",
                            "7-Nov-2020",
                        ],
                        "days": [
                            "2020-10-31",
                            "2020-11-01",
                            "2020-11-02",
                            "2020-11-03",
                            "2020-11-04",
                            "2020-11-05",
                            "2020-11-06",
                            "2020-11-07",
                        ],
                    }
                ],
            )

        def test_last14days_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-11-01 05:20:00",
                    "2020-11-02 10:22:00",
                    "2020-11-04 10:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-10 08:25:00",
                ],
                date_from="-14d",
                query_time="2020-11-14 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 6.0,
                        "data": [0.0, 1.0, 1.0, 0.0, 1.0, 2.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
                        "labels": [
                            "31-Oct-2020",
                            "1-Nov-2020",
                            "2-Nov-2020",
                            "3-Nov-2020",
                            "4-Nov-2020",
                            "5-Nov-2020",
                            "6-Nov-2020",
                            "7-Nov-2020",
                            "8-Nov-2020",
                            "9-Nov-2020",
                            "10-Nov-2020",
                            "11-Nov-2020",
                            "12-Nov-2020",
                            "13-Nov-2020",
                            "14-Nov-2020",
                        ],
                        "days": [
                            "2020-10-31",
                            "2020-11-01",
                            "2020-11-02",
                            "2020-11-03",
                            "2020-11-04",
                            "2020-11-05",
                            "2020-11-06",
                            "2020-11-07",
                            "2020-11-08",
                            "2020-11-09",
                            "2020-11-10",
                            "2020-11-11",
                            "2020-11-12",
                            "2020-11-13",
                            "2020-11-14",
                        ],
                    }
                ],
            )

        def test_last30days_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-11-01 05:20:00",
                    "2020-11-11 10:22:00",
                    "2020-11-24 10:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-10 08:25:00",
                ],
                date_from="-30d",
                interval="week",
                query_time="2020-11-30 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 6.0,
                        "data": [0.0, 3.0, 2.0, 0.0, 1.0, 0.0],
                        "labels": [
                            "25-Oct-2020",
                            "1-Nov-2020",
                            "8-Nov-2020",
                            "15-Nov-2020",
                            "22-Nov-2020",
                            "29-Nov-2020",
                        ],
                        "days": ["2020-10-25", "2020-11-01", "2020-11-08", "2020-11-15", "2020-11-22", "2020-11-29"],
                    }
                ],
            )

        def test_last90days_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-09-01 05:20:00",
                    "2020-10-05 05:20:00",
                    "2020-10-20 05:20:00",
                    "2020-11-01 05:20:00",
                    "2020-11-11 10:22:00",
                    "2020-11-24 10:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-10 08:25:00",
                ],
                date_from="-90d",
                interval="month",
                query_time="2020-11-30 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 9,
                        "data": [1, 2, 6],
                        "labels": ["1-Sep-2020", "1-Oct-2020", "1-Nov-2020"],
                        "days": ["2020-09-01", "2020-10-01", "2020-11-01"],
                    }
                ],
            )

        def test_this_month_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-11-01 05:20:00",
                    "2020-11-11 10:22:00",
                    "2020-11-24 10:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-10 08:25:00",
                ],
                date_from="mStart",
                interval="month",
                query_time="2020-11-30 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 6,
                        "data": [6],
                        "labels": ["1-Nov-2020"],
                        "days": ["2020-11-01"],
                    }
                ],
            )

        def test_previous_month_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-11-01 05:20:00",
                    "2020-11-11 10:22:00",
                    "2020-11-24 10:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-05 08:25:00",
                    "2020-11-10 08:25:00",
                ],
                date_from="-1mStart",
                date_to="-1mEnd",
                interval="month",
                query_time="2020-12-30 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 6,
                        "data": [6],
                        "labels": ["1-Nov-2020"],
                        "days": ["2020-11-01"],
                    }
                ],
            )

        def test_year_to_date_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-01-01 05:20:00",
                    "2020-01-11 10:22:00",
                    "2020-02-24 10:25:00",
                    "2020-02-05 08:25:00",
                    "2020-03-05 08:25:00",
                    "2020-05-10 08:25:00",
                ],
                date_from="yStart",
                interval="month",
                query_time="2020-04-30 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 5.0,
                        "data": [2.0, 2.0, 1.0, 0.0],
                        "labels": ["1-Jan-2020", "1-Feb-2020", "1-Mar-2020", "1-Apr-2020"],
                        "days": ["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"],
                    }
                ],
            )

        def test_all_time_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-01-01 05:20:00",
                    "2020-01-11 10:22:00",
                    "2020-02-24 10:25:00",
                    "2020-02-05 08:25:00",
                    "2020-03-05 08:25:00",
                ],
                date_from="all",
                interval="month",
                query_time="2020-04-30 10:20:00",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 5.0,
                        "data": [2.0, 2.0, 1.0, 0.0],
                        "labels": ["1-Jan-2020", "1-Feb-2020", "1-Mar-2020", "1-Apr-2020"],
                        "days": ["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"],
                    }
                ],
            )

        def test_custom_range_timerange(self):
            self._test_events_with_dates(
                dates=[
                    "2020-01-05 05:20:00",
                    "2020-01-05 10:22:00",
                    "2020-01-04 10:25:00",
                    "2020-01-11 08:25:00",
                    "2020-01-09 08:25:00",
                ],
                date_from="2020-01-05",
                query_time="2020-01-10",
                result=[
                    {
                        "action": {
                            "id": "event_name",
                            "type": "events",
                            "order": None,
                            "name": "event_name",
                            "custom_name": None,
                            "math": None,
                            "math_property": None,
                            "properties": [],
                        },
                        "label": "event_name",
                        "count": 3.0,
                        "data": [2.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                        "labels": ["5-Jan-2020", "6-Jan-2020", "7-Jan-2020", "8-Jan-2020", "9-Jan-2020", "10-Jan-2020"],
                        "days": ["2020-01-05", "2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09", "2020-01-10"],
                    }
                ],
            )

        @test_with_materialized_columns(["$some_property"])
        def test_property_filtering(self):
            self._create_events()
            with freeze_time("2020-01-04"):
                response = trends().run(
                    Filter(
                        data={
                            "properties": [{"key": "$some_property", "value": "value"}],
                            "events": [{"id": "sign up"}],
                        }
                    ),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
            self.assertEqual(response[0]["data"][4], 1.0)
            self.assertEqual(response[0]["labels"][5], "2-Jan-2020")
            self.assertEqual(response[0]["data"][5], 0)

        @test_with_materialized_columns(person_properties=["name"])
        def test_filter_events_by_cohort(self):
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person_1"], properties={"name": "John"})
            person2 = person_factory(team_id=self.team.pk, distinct_ids=["person_2"], properties={"name": "Jane"})

            event1 = event_factory(
                event="event_name", team=self.team, distinct_id="person_1", properties={"$browser": "Safari"},
            )
            event2 = event_factory(
                event="event_name", team=self.team, distinct_id="person_2", properties={"$browser": "Chrome"},
            )
            event3 = event_factory(
                event="event_name", team=self.team, distinct_id="person_2", properties={"$browser": "Safari"},
            )

            cohort = cohort_factory(
                team=self.team,
                name="cohort1",
                groups=[{"properties": [{"key": "name", "value": "Jane", "type": "person"}]}],
            )

            response = trends().run(
                Filter(
                    data={
                        "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                        "events": [{"id": "event_name"}],
                    },
                    team=self.team,
                ),
                self.team,
            )

            self.assertEqual(response[0]["count"], 2)
            self.assertEqual(response[0]["data"][-1], 2)

        def test_response_empty_if_no_events(self):
            self._create_events()
            response = trends().run(Filter(data={"date_from": "2012-12-12"}), self.team)
            self.assertEqual(response, [])

        def test_interval_filtering(self):
            self._create_events(use_time=True)

            # test minute
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(data={"date_from": "2020-01-01", "interval": "minute", "events": [{"id": "sign up"}]}),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][6], "1-Jan-2020 00:06")
            self.assertEqual(response[0]["data"][6], 3.0)

            # test hour
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(data={"date_from": "2019-12-24", "interval": "hour", "events": [{"id": "sign up"}]}),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][3], "24-Dec-2019 03:00")
            self.assertEqual(response[0]["data"][3], 1.0)
            # 217 - 24 - 1
            self.assertEqual(response[0]["data"][192], 3.0)

            # test week
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(
                        data={
                            #  2019-11-24 is a Sunday, i.e. beginning of our week
                            "date_from": "2019-11-24",
                            "interval": "week",
                            "events": [{"id": "sign up"}],
                        }
                    ),
                    self.team,
                )
            self.assertEqual(
                response[0]["labels"][:5], ["24-Nov-2019", "1-Dec-2019", "8-Dec-2019", "15-Dec-2019", "22-Dec-2019"]
            )
            self.assertEqual(response[0]["data"][:5], [0.0, 0.0, 0.0, 0.0, 1.0])

            # test month
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(data={"date_from": "2019-9-24", "interval": "month", "events": [{"id": "sign up"}]}),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][0], "1-Sep-2019")
            self.assertEqual(response[0]["data"][0], 0)
            self.assertEqual(response[0]["labels"][3], "1-Dec-2019")
            self.assertEqual(response[0]["data"][3], 1.0)
            self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
            self.assertEqual(response[0]["data"][4], 4.0)

            with freeze_time("2020-01-02 23:30"):
                event_factory(team=self.team, event="sign up", distinct_id="blabla")

            # test today + hourly
            with freeze_time("2020-01-02T23:31:00Z"):
                response = trends().run(
                    Filter(data={"date_from": "dStart", "interval": "hour", "events": [{"id": "sign up"}]}), self.team
                )
            self.assertEqual(response[0]["labels"][23], "2-Jan-2020 23:00")
            self.assertEqual(response[0]["data"][23], 1.0)

        def test_breakdown_label(self):
            entity = Entity({"id": "$pageview", "name": "$pageview", "type": TREND_FILTER_TYPE_EVENTS})
            num_label = breakdown_label(entity, 1)
            self.assertEqual(num_label, {"label": "$pageview - 1", "breakdown_value": 1})

            string_label = breakdown_label(entity, "Chrome")
            self.assertEqual(string_label, {"label": "$pageview - Chrome", "breakdown_value": "Chrome"})

            nan_label = breakdown_label(entity, "nan")
            self.assertEqual(nan_label, {"label": "$pageview - Other", "breakdown_value": "Other"})

            none_label = breakdown_label(entity, "None")
            self.assertEqual(none_label, {"label": "$pageview - Other", "breakdown_value": "Other"})

            cohort_all_label = breakdown_label(entity, "cohort_all")
            self.assertEqual(cohort_all_label, {"label": "$pageview - all users", "breakdown_value": "all"})

            cohort = cohort_factory(team=self.team, name="cohort1", groups=[{"properties": {"name": "Jane"}}])
            cohort_label = breakdown_label(entity, f"cohort_{cohort.pk}")
            self.assertEqual(cohort_label, {"label": f"$pageview - {cohort.name}", "breakdown_value": cohort.pk})

        def test_breakdown_filtering(self):
            self._create_events()

            # test bool breakdown
            with freeze_time("2020-01-04T13:01:01Z"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "$bool_prop",
                            "events": [
                                {"id": "sign up", "name": "sign up", "type": "events", "order": 0,},
                                {"id": "no events"},
                            ],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["label"], "sign up - False")
            self.assertEqual(response[1]["label"], "sign up - True")
            self.assertEqual(response[2]["label"], "sign up - Other")

            # test breakdown filtering
            with freeze_time("2020-01-04T13:01:01Z"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "$some_property",
                            "events": [
                                {"id": "sign up", "name": "sign up", "type": "events", "order": 0,},
                                {"id": "no events"},
                            ],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["label"], "sign up - Other")
            self.assertEqual(response[1]["label"], "sign up - other_value")
            self.assertEqual(response[2]["label"], "sign up - value")
            self.assertEqual(response[3]["label"], "no events - Other")

            self.assertEqual(sum(response[0]["data"]), 2)
            self.assertEqual(response[0]["data"][4 + 7], 2)
            self.assertEqual(response[0]["breakdown_value"], "Other")

            self.assertEqual(sum(response[1]["data"]), 1)
            self.assertEqual(response[1]["data"][5 + 7], 1)
            self.assertEqual(response[1]["breakdown_value"], "other_value")

            # check numerical breakdown
            with freeze_time("2020-01-04T13:01:01Z"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "$some_numerical_prop",
                            "events": [
                                {"id": "sign up", "name": "sign up", "type": "events", "order": 0,},
                                {"id": "no events"},
                            ],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["label"], "sign up - Other")
            self.assertEqual(response[0]["count"], 4.0)
            self.assertEqual(response[1]["label"], "sign up - 80")
            self.assertEqual(response[1]["count"], 1.0)
            self.assertTrue(
                "aggregated_value" not in response[0]
            )  # should not have aggregated value unless it's a table or pie query

        def test_breakdown_filtering_limit(self):
            self._create_breakdown_events()
            with freeze_time("2020-01-04T13:01:01Z"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "$some_property",
                            "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0}],
                        }
                    ),
                    self.team,
                )
            self.assertEqual(len(response), 25)  # We fetch 25 to see if there are more ethan 20 values

        def test_breakdown_user_props_with_filter(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person1"], properties={"email": "test@posthog.com"})
            person_factory(team_id=self.team.pk, distinct_ids=["person2"], properties={"email": "test@gmail.com"})
            event_factory(event="sign up", distinct_id="person1", team=self.team, properties={"key": "val"})
            event_factory(event="sign up", distinct_id="person2", team=self.team, properties={"key": "val"})
            response = trends().run(
                Filter(
                    data={
                        "date_from": "-14d",
                        "breakdown": "email",
                        "breakdown_type": "person",
                        "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0}],
                        "properties": [
                            {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"},
                            {"key": "key", "value": "val"},
                        ],
                    }
                ),
                self.team,
            )
            self.assertEqual(len(response), 1)
            self.assertEqual(response[0]["breakdown_value"], "test@gmail.com")

        @test_with_materialized_columns(["key"])
        def test_breakdown_with_filter(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person1"], properties={"email": "test@posthog.com"})
            person_factory(team_id=self.team.pk, distinct_ids=["person2"], properties={"email": "test@gmail.com"})
            event_factory(event="sign up", distinct_id="person1", team=self.team, properties={"key": "val"})
            event_factory(event="sign up", distinct_id="person2", team=self.team, properties={"key": "oh"})
            response = trends().run(
                Filter(
                    data={
                        "date_from": "-14d",
                        "breakdown": "key",
                        "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
                        "properties": [{"key": "key", "value": "oh", "operator": "not_icontains"}],
                    }
                ),
                self.team,
            )
            self.assertEqual(len(response), 1)
            self.assertEqual(response[0]["breakdown_value"], "val")

        def test_action_filtering(self):
            sign_up_action, person = self._create_events()
            action_response = trends().run(Filter(data={"actions": [{"id": sign_up_action.id}]}), self.team)
            event_response = trends().run(Filter(data={"events": [{"id": "sign up"}]}), self.team)
            self.assertEqual(len(action_response), 1)

            self.assertEntityResponseEqual(action_response, event_response)

        def test_trends_for_non_existing_action(self):
            with freeze_time("2020-01-04"):
                response = trends().run(Filter(data={"actions": [{"id": 50000000}]}), self.team)
            self.assertEqual(len(response), 0)

            with freeze_time("2020-01-04"):
                response = trends().run(Filter(data={"events": [{"id": "DNE"}]}), self.team)
            self.assertEqual(response[0]["data"], [0, 0, 0, 0, 0, 0, 0, 0])

        @test_with_materialized_columns(person_properties=["email", "bar"])
        def test_trends_regression_filtering_by_action_with_person_properties(self):
            person1 = person_factory(
                team_id=self.team.pk, properties={"email": "foo@example.com", "bar": "aa"}, distinct_ids=["d1"]
            )
            person2 = person_factory(
                team_id=self.team.pk, properties={"email": "bar@example.com", "bar": "bb"}, distinct_ids=["d2"]
            )
            person2 = person_factory(
                team_id=self.team.pk, properties={"email": "efg@example.com", "bar": "ab"}, distinct_ids=["d3"]
            )
            person3 = person_factory(team_id=self.team.pk, properties={"bar": "aa"}, distinct_ids=["d4"])

            with freeze_time("2020-01-02 16:34:34"):
                event_factory(team=self.team, event="$pageview", distinct_id="d1")
                event_factory(team=self.team, event="$pageview", distinct_id="d2")
                event_factory(team=self.team, event="$pageview", distinct_id="d3")
                event_factory(team=self.team, event="$pageview", distinct_id="d4")

            event_filtering_action = Action.objects.create(team=self.team, name="$pageview from non-internal")
            ActionStep.objects.create(
                action=event_filtering_action,
                event="$pageview",
                properties=[{"key": "bar", "type": "person", "value": "a", "operator": "icontains"}],
            )
            event_filtering_action.calculate_events()

            with freeze_time("2020-01-04T13:01:01Z"):
                response = trends().run(Filter({"actions": [{"id": event_filtering_action.id}],}), self.team)
            self.assertEqual(len(response), 1)
            self.assertEqual(response[0]["count"], 3)

            with freeze_time("2020-01-04T13:01:01Z"):
                response_with_email_filter = trends().run(
                    Filter(
                        {
                            "actions": [{"id": event_filtering_action.id}],
                            "properties": [{"key": "email", "type": "person", "value": "is_set", "operator": "is_set"}],
                        }
                    ),
                    self.team,
                )
            self.assertEqual(len(response_with_email_filter), 1)
            self.assertEqual(response_with_email_filter[0]["count"], 2)

        def test_dau_filtering(self):
            sign_up_action, person = self._create_events()

            with freeze_time("2020-01-02"):
                person_factory(team_id=self.team.pk, distinct_ids=["someone_else"])
                event_factory(team=self.team, event="sign up", distinct_id="someone_else")

            sign_up_action.calculate_events()

            with freeze_time("2020-01-04"):
                action_response = trends().run(
                    Filter(data={"actions": [{"id": sign_up_action.id, "math": "dau"}]}), self.team
                )
                response = trends().run(Filter(data={"events": [{"id": "sign up", "math": "dau"}]}), self.team)

            self.assertEqual(response[0]["data"][4], 1)
            self.assertEqual(response[0]["data"][5], 2)
            self.assertEntityResponseEqual(action_response, response)

        @test_with_materialized_columns(["$some_property"])
        def test_dau_with_breakdown_filtering(self):
            sign_up_action, _ = self._create_events()
            with freeze_time("2020-01-02"):
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$some_property": "other_value"},
                )
            with freeze_time("2020-01-04"):
                action_response = trends().run(
                    Filter(data={"breakdown": "$some_property", "actions": [{"id": sign_up_action.id, "math": "dau"}]}),
                    self.team,
                )
                event_response = trends().run(
                    Filter(data={"breakdown": "$some_property", "events": [{"id": "sign up", "math": "dau"}]}),
                    self.team,
                )

            self.assertEqual(event_response[0]["label"], "sign up - other_value")
            self.assertEqual(event_response[1]["label"], "sign up - value")
            self.assertEqual(event_response[2]["label"], "sign up - Other")

            self.assertEqual(sum(event_response[0]["data"]), 1)
            self.assertEqual(event_response[0]["data"][5], 1)

            self.assertEqual(sum(event_response[2]["data"]), 1)
            self.assertEqual(event_response[2]["data"][4], 1)  # property not defined

            self.assertEntityResponseEqual(action_response, event_response)

        def _create_maths_events(self, values):
            sign_up_action, person = self._create_events()
            person_factory(team_id=self.team.pk, distinct_ids=["someone_else"])
            for value in values:
                event_factory(
                    team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": value}
                )
            event_factory(team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": None})
            calculate_actions_from_last_calculation()
            return sign_up_action

        def _test_math_property_aggregation(self, math_property, values, expected_value):
            sign_up_action = self._create_maths_events(values)

            action_response = trends().run(
                Filter(
                    data={"actions": [{"id": sign_up_action.id, "math": math_property, "math_property": "some_number"}]}
                ),
                self.team,
            )
            event_response = trends().run(
                Filter(data={"events": [{"id": "sign up", "math": math_property, "math_property": "some_number"}]}),
                self.team,
            )
            # :TRICKY: Work around clickhouse functions not being 100%
            self.assertAlmostEqual(action_response[0]["data"][-1], expected_value, delta=0.5)
            self.assertEntityResponseEqual(action_response, event_response)

        @test_with_materialized_columns(["some_number"])
        def test_sum_filtering(self):
            self._test_math_property_aggregation("sum", values=[2, 3, 5.5, 7.5], expected_value=18)

        @test_with_materialized_columns(["some_number"])
        def test_avg_filtering(self):
            self._test_math_property_aggregation("avg", values=[2, 3, 5.5, 7.5], expected_value=4.5)

        @test_with_materialized_columns(["some_number"])
        def test_min_filtering(self):
            self._test_math_property_aggregation("min", values=[2, 3, 5.5, 7.5], expected_value=2)

        @test_with_materialized_columns(["some_number"])
        def test_max_filtering(self):
            self._test_math_property_aggregation("max", values=[2, 3, 5.5, 7.5], expected_value=7.5)

        @test_with_materialized_columns(["some_number"])
        def test_median_filtering(self):
            self._test_math_property_aggregation("median", values=range(101, 201), expected_value=150)

        @test_with_materialized_columns(["some_number"])
        def test_p90_filtering(self):
            self._test_math_property_aggregation("p90", values=range(101, 201), expected_value=190)

        @test_with_materialized_columns(["some_number"])
        def test_p95_filtering(self):
            self._test_math_property_aggregation("p95", values=range(101, 201), expected_value=195)

        @test_with_materialized_columns(["some_number"])
        def test_p99_filtering(self):
            self._test_math_property_aggregation("p99", values=range(101, 201), expected_value=199)

        @test_with_materialized_columns(["some_number"])
        def test_avg_filtering_non_number_resiliency(self):
            sign_up_action, person = self._create_events()
            person_factory(team_id=self.team.pk, distinct_ids=["someone_else"])
            event_factory(team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": 2})
            event_factory(team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": "x"})
            event_factory(team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": None})
            event_factory(team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": 8})
            calculate_actions_from_last_calculation()
            action_response = trends().run(
                Filter(data={"actions": [{"id": sign_up_action.id, "math": "avg", "math_property": "some_number"}]}),
                self.team,
            )
            event_response = trends().run(
                Filter(data={"events": [{"id": "sign up", "math": "avg", "math_property": "some_number"}]}), self.team
            )
            self.assertEqual(action_response[0]["data"][-1], 5)
            self.assertEntityResponseEqual(action_response, event_response)

        @test_with_materialized_columns(["$some_property"])
        def test_per_entity_filtering(self):
            self._create_events()
            with freeze_time("2020-01-04T13:00:01Z"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-7d",
                            "events": [
                                {"id": "sign up", "properties": [{"key": "$some_property", "value": "value"}],},
                                {"id": "sign up", "properties": [{"key": "$some_property", "value": "other_value"}],},
                            ],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
            self.assertEqual(response[0]["data"][4], 1)
            self.assertEqual(response[0]["count"], 1)
            self.assertEqual(response[1]["labels"][5], "2-Jan-2020")
            self.assertEqual(response[1]["data"][5], 1)
            self.assertEqual(response[1]["count"], 1)

        def _create_multiple_people(self):
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person1"], properties={"name": "person1"})
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person1",
                timestamp="2020-01-01T12:00:00Z",
                properties={"order": "1"},
            )

            person2 = person_factory(team_id=self.team.pk, distinct_ids=["person2"], properties={"name": "person2"})
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person2",
                timestamp="2020-01-01T12:00:00Z",
                properties={"order": "1"},
            )
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person2",
                timestamp="2020-01-02T12:00:00Z",
                properties={"order": "2"},
            )
            # same day
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person2",
                timestamp="2020-01-02T12:00:00Z",
                properties={"order": "2"},
            )

            person3 = person_factory(team_id=self.team.pk, distinct_ids=["person3"], properties={"name": "person3"})
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person3",
                timestamp="2020-01-01T12:00:00Z",
                properties={"order": "1"},
            )
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person3",
                timestamp="2020-01-02T12:00:00Z",
                properties={"order": "2"},
            )
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person3",
                timestamp="2020-01-03T12:00:00Z",
                properties={"order": "2"},
            )

            person4 = person_factory(team_id=self.team.pk, distinct_ids=["person4"], properties={"name": "person4"})
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person4",
                timestamp="2020-01-05T12:00:00Z",
                properties={"order": "1"},
            )

            return (person1, person2, person3, person4)

        @test_with_materialized_columns(person_properties=["name"])
        def test_person_property_filtering(self):
            self._create_multiple_people()
            with freeze_time("2020-01-04"):
                response = trends().run(
                    Filter(
                        data={
                            "properties": [{"key": "name", "value": "person1", "type": "person",}],
                            "events": [{"id": "watched movie"}],
                        }
                    ),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
            self.assertEqual(response[0]["data"][4], 1.0)
            self.assertEqual(response[0]["labels"][5], "2-Jan-2020")
            self.assertEqual(response[0]["data"][5], 0)

        @test_with_materialized_columns(person_properties=["name"])
        def test_entity_person_property_filtering(self):
            self._create_multiple_people()
            with freeze_time("2020-01-04"):
                response = trends().run(
                    Filter(
                        data={
                            "events": [
                                {
                                    "id": "watched movie",
                                    "properties": [{"key": "name", "value": "person1", "type": "person",}],
                                }
                            ],
                        }
                    ),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
            self.assertEqual(response[0]["data"][4], 1.0)
            self.assertEqual(response[0]["labels"][5], "2-Jan-2020")
            self.assertEqual(response[0]["data"][5], 0)

        def test_breakdown_by_empty_cohort(self):
            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
            event_factory(
                team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-04T12:00:00Z",
            )

            with freeze_time("2020-01-04T13:01:01Z"):
                event_response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": json.dumps(["all"]),
                            "breakdown_type": "cohort",
                            "events": [{"id": "$pageview", "type": "events", "order": 0}],
                        }
                    ),
                    self.team,
                )

            self.assertEqual(event_response[0]["label"], "$pageview - all users")
            self.assertEqual(sum(event_response[0]["data"]), 1)

        @test_with_materialized_columns(person_properties=["name"], verify_no_jsonextract=False)
        def test_breakdown_by_cohort(self):
            person1, person2, person3, person4 = self._create_multiple_people()
            cohort = cohort_factory(name="cohort1", team=self.team, groups=[{"properties": {"name": "person1"}}])
            cohort2 = cohort_factory(name="cohort2", team=self.team, groups=[{"properties": {"name": "person2"}}])
            cohort3 = cohort_factory(
                name="cohort3",
                team=self.team,
                groups=[{"properties": {"name": "person1"}}, {"properties": {"name": "person2"}},],
            )
            action = action_factory(name="watched movie", team=self.team)
            action.calculate_events()

            with freeze_time("2020-01-04T13:01:01Z"):
                action_response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": json.dumps([cohort.pk, cohort2.pk, cohort3.pk, "all"]),
                            "breakdown_type": "cohort",
                            "actions": [{"id": action.pk, "type": "actions", "order": 0}],
                        }
                    ),
                    self.team,
                )
                event_response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": json.dumps([cohort.pk, cohort2.pk, cohort3.pk, "all"]),
                            "breakdown_type": "cohort",
                            "events": [{"id": "watched movie", "name": "watched movie", "type": "events", "order": 0,}],
                        }
                    ),
                    self.team,
                )

            counts = {}
            break_val = {}
            for res in event_response:
                counts[res["label"]] = sum(res["data"])
                break_val[res["label"]] = res["breakdown_value"]

            self.assertEqual(counts["watched movie - cohort1"], 1)
            self.assertEqual(counts["watched movie - cohort2"], 3)
            self.assertEqual(counts["watched movie - cohort3"], 4)
            self.assertEqual(counts["watched movie - all users"], 7)

            self.assertEqual(break_val["watched movie - cohort1"], cohort.pk)
            self.assertEqual(break_val["watched movie - cohort2"], cohort2.pk)
            self.assertEqual(break_val["watched movie - cohort3"], cohort3.pk)
            self.assertEqual(break_val["watched movie - all users"], "all")

            self.assertEntityResponseEqual(
                event_response, action_response,
            )

        @test_with_materialized_columns(verify_no_jsonextract=False)
        def test_interval_filtering_breakdown(self):
            self._create_events(use_time=True)
            cohort = cohort_factory(
                name="cohort1",
                team=self.team,
                groups=[{"properties": [{"key": "$some_prop", "value": "some_val", "type": "person"}]}],
            )

            # test minute
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "2020-01-01",
                            "interval": "minute",
                            "events": [{"id": "sign up"}],
                            "breakdown": json.dumps([cohort.pk]),
                            "breakdown_type": "cohort",
                        }
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["labels"][6], "1-Jan-2020 00:06")
            self.assertEqual(response[0]["data"][6], 3.0)

            # test hour
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "2019-12-24",
                            "interval": "hour",
                            "events": [{"id": "sign up"}],
                            "breakdown": json.dumps([cohort.pk]),
                            "breakdown_type": "cohort",
                        }
                    ),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][3], "24-Dec-2019 03:00")
            self.assertEqual(response[0]["data"][3], 1.0)
            # 217 - 24 - 1
            self.assertEqual(response[0]["data"][192], 3.0)

            # test week
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(
                        data={
                            # 2019-11-24 is a Sunday
                            "date_from": "2019-11-24",
                            "interval": "week",
                            "events": [{"id": "sign up"}],
                            "breakdown": json.dumps([cohort.pk]),
                            "breakdown_type": "cohort",
                        }
                    ),
                    self.team,
                )

            self.assertEqual(
                response[0]["labels"][:5], ["24-Nov-2019", "1-Dec-2019", "8-Dec-2019", "15-Dec-2019", "22-Dec-2019"]
            )
            self.assertEqual(response[0]["data"][:5], [0.0, 0.0, 0.0, 0.0, 1.0])

            # test month
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "2019-9-24",
                            "interval": "month",
                            "events": [{"id": "sign up"}],
                            "breakdown": json.dumps([cohort.pk]),
                            "breakdown_type": "cohort",
                        }
                    ),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][3], "1-Dec-2019")
            self.assertEqual(response[0]["data"][3], 1.0)
            self.assertEqual(response[0]["labels"][4], "1-Jan-2020")
            self.assertEqual(response[0]["data"][4], 4.0)

            with freeze_time("2020-01-02 23:30"):
                event_factory(team=self.team, event="sign up", distinct_id="blabla")

            # test today + hourly
            with freeze_time("2020-01-02T23:31:00Z"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "dStart",
                            "interval": "hour",
                            "events": [{"id": "sign up"}],
                            "breakdown": json.dumps([cohort.pk]),
                            "breakdown_type": "cohort",
                        }
                    ),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][23], "2-Jan-2020 23:00")
            self.assertEqual(response[0]["data"][23], 1.0)

        def test_breakdown_by_person_property(self):
            person1, person2, person3, person4 = self._create_multiple_people()
            action = action_factory(name="watched movie", team=self.team)

            with freeze_time("2020-01-04T13:01:01Z"):
                action_response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "name",
                            "breakdown_type": "person",
                            "actions": [{"id": action.pk, "type": "actions", "order": 0}],
                        }
                    ),
                    self.team,
                )
                event_response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "name",
                            "breakdown_type": "person",
                            "events": [{"id": "watched movie", "name": "watched movie", "type": "events", "order": 0,}],
                        }
                    ),
                    self.team,
                )

            self.assertListEqual(
                sorted([res["breakdown_value"] for res in event_response]), ["person1", "person2", "person3"]
            )

            for response in event_response:
                if response["breakdown_value"] == "person1":
                    self.assertEqual(response["count"], 1)
                    self.assertEqual(response["label"], "watched movie - person1")
                if response["breakdown_value"] == "person2":
                    self.assertEqual(response["count"], 3)
                if response["breakdown_value"] == "person3":
                    self.assertEqual(response["count"], 3)

            self.assertEntityResponseEqual(
                event_response, action_response,
            )

        def test_breakdown_by_property_pie(self):
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person1"])
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person1",
                timestamp="2020-01-01T12:00:00Z",
                properties={"fake_prop": "value_1"},
            )

            person2 = person_factory(team_id=self.team.pk, distinct_ids=["person2"])
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person2",
                timestamp="2020-01-01T12:00:00Z",
                properties={"fake_prop": "value_1"},
            )
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person2",
                timestamp="2020-01-02T12:00:00Z",
                properties={"fake_prop": "value_2"},
            )

            person3 = person_factory(team_id=self.team.pk, distinct_ids=["person3"])
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person3",
                timestamp="2020-01-01T12:00:00Z",
                properties={"fake_prop": "value_1"},
            )

            person4 = person_factory(team_id=self.team.pk, distinct_ids=["person4"])
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person4",
                timestamp="2020-01-05T12:00:00Z",
                properties={"fake_prop": "value_1"},
            )

            with freeze_time("2020-01-04T13:01:01Z"):
                data = {
                    "date_from": "-14d",
                    "breakdown": "fake_prop",
                    "breakdown_type": "event",
                    "display": "ActionsPie",
                    "events": [
                        {"id": "watched movie", "name": "watched movie", "type": "events", "order": 0, "math": "dau",}
                    ],
                }
                event_response = trends().run(Filter(data=data), self.team,)
                event_response = sorted(event_response, key=lambda resp: resp["breakdown_value"])

                entity = Entity({"id": "watched movie", "type": "events", "math": "dau"})
                data.update({"breakdown_value": "value_1"})
                people = self._get_trend_people(Filter(data=data), entity)

                # TODO: improve ee/postgres handling
                value_1_ids = sorted([person["id"] for person in people])
                self.assertTrue(
                    value_1_ids == sorted([person1.uuid, person2.uuid, person3.uuid])
                    or value_1_ids == sorted([person1.pk, person2.pk, person3.pk])
                )

                data.update({"breakdown_value": "value_2"})
                people = self._get_trend_people(Filter(data=data), entity)

                value_2_ids = [person["id"] for person in people]
                self.assertTrue(value_2_ids == [person2.uuid] or value_2_ids == [person2.pk])

        @test_with_materialized_columns(person_properties=["name"])
        def test_breakdown_by_person_property_pie(self):
            self._create_multiple_people()

            with freeze_time("2020-01-04T13:01:01Z"):
                event_response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "name",
                            "breakdown_type": "person",
                            "display": "ActionsPie",
                            "events": [
                                {
                                    "id": "watched movie",
                                    "name": "watched movie",
                                    "type": "events",
                                    "order": 0,
                                    "math": "dau",
                                }
                            ],
                        }
                    ),
                    self.team,
                )
                event_response = sorted(event_response, key=lambda resp: resp["breakdown_value"])
                self.assertDictContainsSubset({"breakdown_value": "person1", "aggregated_value": 1}, event_response[0])
                self.assertDictContainsSubset({"breakdown_value": "person2", "aggregated_value": 1}, event_response[1])
                self.assertDictContainsSubset({"breakdown_value": "person3", "aggregated_value": 1}, event_response[2])

        def test_filter_test_accounts(self):
            p1 = person_factory(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp="2020-01-11T12:00:00Z",
                properties={"key": "val"},
            )

            p2 = person_factory(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="p2",
                timestamp="2020-01-11T12:00:00Z",
                properties={"key": "val"},
            )
            self.team.test_account_filters = [{"key": "name", "value": "p1", "operator": "is_not", "type": "person"}]
            self.team.save()
            data = {
                "date_from": "2020-01-01T00:00:00Z",
                "date_to": "2020-01-12T00:00:00Z",
                "events": [{"id": "$pageview", "type": "events", "order": 0}],
                "filter_test_accounts": "true",
            }
            filter = Filter(data=data, team=self.team)
            filter_2 = Filter(data={**data, "filter_test_accounts": "false",}, team=self.team)
            filter_3 = Filter(data={**data, "breakdown": "key"}, team=self.team)
            result = trends().run(filter, self.team,)
            self.assertEqual(result[0]["count"], 1)
            result = trends().run(filter_2, self.team,)
            self.assertEqual(result[0]["count"], 2)
            result = trends().run(filter_3, self.team,)
            self.assertEqual(result[0]["count"], 1)

        @test_with_materialized_columns(person_properties=["name"])
        def test_filter_test_accounts_cohorts(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person_1"], properties={"name": "John"})
            person_factory(team_id=self.team.pk, distinct_ids=["person_2"], properties={"name": "Jane"})

            event_factory(event="event_name", team=self.team, distinct_id="person_1")
            event_factory(event="event_name", team=self.team, distinct_id="person_2")
            event_factory(event="event_name", team=self.team, distinct_id="person_2")

            cohort = cohort_factory(
                team=self.team,
                name="cohort1",
                groups=[{"properties": [{"key": "name", "value": "Jane", "type": "person"}]}],
            )
            self.team.test_account_filters = [{"key": "id", "value": cohort.pk, "type": "cohort"}]
            self.team.save()

            response = trends().run(
                Filter(data={"events": [{"id": "event_name"}], "filter_test_accounts": True}, team=self.team),
                self.team,
            )

            self.assertEqual(response[0]["count"], 2)
            self.assertEqual(response[0]["data"][-1], 2)

        def test_filter_by_precalculated_cohort(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person_1"], properties={"name": "John"})
            person_factory(team_id=self.team.pk, distinct_ids=["person_2"], properties={"name": "Jane"})

            event_factory(event="event_name", team=self.team, distinct_id="person_1")
            event_factory(event="event_name", team=self.team, distinct_id="person_2")
            event_factory(event="event_name", team=self.team, distinct_id="person_2")

            cohort = cohort_factory(
                team=self.team,
                name="cohort1",
                groups=[{"properties": [{"key": "name", "value": "Jane", "type": "person"}]}],
            )
            cohort.calculate_people_ch()
            with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
                response = trends().run(
                    Filter(
                        data={
                            "events": [{"id": "event_name"}],
                            "properties": [{"type": "cohort", "key": "id", "value": cohort.pk}],
                        },
                        team=self.team,
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["count"], 2)
            self.assertEqual(response[0]["data"][-1], 2)

        def test_breakdown_filter_by_precalculated_cohort(self):
            person_factory(team_id=self.team.pk, distinct_ids=["person_1"], properties={"name": "John"})
            person_factory(team_id=self.team.pk, distinct_ids=["person_2"], properties={"name": "Jane"})

            event_factory(event="event_name", team=self.team, distinct_id="person_1")
            event_factory(event="event_name", team=self.team, distinct_id="person_2")
            event_factory(event="event_name", team=self.team, distinct_id="person_2")

            cohort = cohort_factory(
                team=self.team,
                name="cohort1",
                groups=[{"properties": [{"key": "name", "value": "Jane", "type": "person"}]}],
            )
            cohort.calculate_people_ch()

            with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
                response = trends().run(
                    Filter(
                        data={
                            "events": [{"id": "event_name"}],
                            "properties": [{"type": "cohort", "key": "id", "value": cohort.pk}],
                            "breakdown": "name",
                            "breakdown_type": "person",
                        },
                        team=self.team,
                    ),
                    self.team,
                )

            self.assertEqual(response[0]["count"], 2)
            self.assertEqual(response[0]["data"][-1], 2)

        def test_bar_chart_by_value(self):
            self._create_events()

            with freeze_time("2020-01-04T13:00:01Z"):
                # with self.assertNumQueries(16):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-7d",
                            "events": [{"id": "sign up"}, {"id": "no events"}],
                            "display": TRENDS_BAR_VALUE,
                        }
                    ),
                    self.team,
                )
            self.assertEqual(response[0]["aggregated_value"], 4)
            self.assertEqual(response[1]["aggregated_value"], 1)
            self.assertEqual(
                response[0]["days"],
                [
                    "2019-12-28",
                    "2019-12-29",
                    "2019-12-30",
                    "2019-12-31",
                    "2020-01-01",
                    "2020-01-02",
                    "2020-01-03",
                    "2020-01-04",
                ],
            )

        @test_with_materialized_columns(["$some_property"])
        def test_breakdown_filtering_bar_chart_by_value(self):
            self._create_events()

            # test breakdown filtering
            with freeze_time("2020-01-04T13:01:01Z"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-7d",
                            "breakdown": "$some_property",
                            "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,},],
                            "display": TRENDS_BAR_VALUE,
                        }
                    ),
                    self.team,
                )

            self.assertEqual(
                response[0]["count"], 2
            )  # postgres returns none for display by value TODO: update clickhouse query to return this also
            self.assertEqual(response[1]["aggregated_value"], 1)
            self.assertEqual(response[2]["aggregated_value"], 1)
            self.assertEqual(
                response[0]["days"],
                [
                    "2019-12-28",
                    "2019-12-29",
                    "2019-12-30",
                    "2019-12-31",
                    "2020-01-01",
                    "2020-01-02",
                    "2020-01-03",
                    "2020-01-04",
                ],
            )

    return TestTrends


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    action.calculate_events()
    return action


def _create_cohort(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    groups = kwargs.pop("groups")
    cohort = Cohort.objects.create(team=team, name=name, groups=groups)
    cohort.calculate_people()
    return cohort


class TestDjangoTrends(trend_test_factory(Trends, Event.objects.create, Person.objects.create, _create_action, _create_cohort)):  # type: ignore
    pass
