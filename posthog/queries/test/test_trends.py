import json

from freezegun import freeze_time

from posthog.api.test.base import BaseTest
from posthog.models import Action, ActionStep, Cohort, Event, Filter, Person, Team
from posthog.queries.trends import Trends


# parameterize tests to reuse in EE
def trend_test_factory(trends):
    class TestTrends(BaseTest):
        def _create_events(self, use_time=False):
            no_events = Action.objects.create(team=self.team, name="no events")
            ActionStep.objects.create(action=no_events, event="no events")

            sign_up_action = Action.objects.create(team=self.team, name="sign up")
            ActionStep.objects.create(action=sign_up_action, event="sign up")

            person = Person.objects.create(team=self.team, distinct_ids=["blabla", "anonymous_id"])
            secondTeam = Team.objects.create(api_token="token123")

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
                Event.objects.create(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$some_property": "value"},
                )

            with freeze_time(freeze_args[1]):
                Event.objects.create(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$some_property": "value"},
                )
                Event.objects.create(team=self.team, event="sign up", distinct_id="anonymous_id")
                Event.objects.create(team=self.team, event="sign up", distinct_id="blabla")
            with freeze_time(freeze_args[2]):
                Event.objects.create(
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "other_value", "$some_numerical_prop": 80,},
                )
                Event.objects.create(team=self.team, event="no events", distinct_id="blabla")

                # second team should have no effect
                Event.objects.create(
                    team=secondTeam,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": "other_value"},
                )
            return sign_up_action, person

        def _create_breakdown_events(self):
            freeze_without_time = ["2020-01-02"]

            sign_up_action = Action.objects.create(team=self.team, name="sign up")
            ActionStep.objects.create(action=sign_up_action, event="sign up")

            with freeze_time(freeze_without_time[0]):
                for i in range(25):
                    Event.objects.create(
                        team=self.team, event="sign up", distinct_id="blabla", properties={"$some_property": i},
                    )

        def _compare_entity_response(self, response1, response2, remove=("action", "label")):
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
            return str(response1[0]) == str(response2[0])

        def test_trends_per_day(self):
            self._create_events()
            with freeze_time("2020-01-04T13:00:01Z"):
                # with self.assertNumQueries(16):
                response = trends().run(
                    Filter(data={"date_from": "-7d", "events": [{"id": "sign up"}, {"id": "no events"}],}), self.team,
                )
            self.assertEqual(response[0]["label"], "sign up")
            self.assertEqual(response[0]["labels"][4], "Wed. 1 January")
            self.assertEqual(response[0]["data"][4], 3.0)
            self.assertEqual(response[0]["labels"][5], "Thu. 2 January")
            self.assertEqual(response[0]["data"][5], 1.0)

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
            self.assertEqual(response[0]["labels"][1], "Thu. 2 January")

        def test_trends_per_day_cumulative(self):
            self._create_events()
            with freeze_time("2020-01-04T13:00:01Z"):
                with self.assertNumQueries(1):
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
            self.assertEqual(response[0]["labels"][4], "Wed. 1 January")
            self.assertEqual(response[0]["data"][4], 3.0)
            self.assertEqual(response[0]["labels"][5], "Thu. 2 January")
            self.assertEqual(response[0]["data"][5], 4.0)

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
            self.assertEqual(no_compare_response[0]["labels"][4], "Wed. 1 January")
            self.assertEqual(no_compare_response[0]["data"][4], 3.0)
            self.assertEqual(no_compare_response[0]["labels"][5], "Thu. 2 January")
            self.assertEqual(no_compare_response[0]["data"][5], 1.0)

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
            self.assertEqual(response[0]["labels"][4], "Wed. 1 January")
            self.assertEqual(response[0]["data"][4], 1.0)
            self.assertEqual(response[0]["labels"][5], "Thu. 2 January")
            self.assertEqual(response[0]["data"][5], 0)

        def test_filter_events_by_cohort(self):
            person1 = Person.objects.create(team=self.team, distinct_ids=["person_1"], properties={"name": "John"})
            person2 = Person.objects.create(team=self.team, distinct_ids=["person_2"], properties={"name": "Jane"})

            event1 = Event.objects.create(
                event="event_name", team=self.team, distinct_id="person_1", properties={"$browser": "Safari"},
            )
            event2 = Event.objects.create(
                event="event_name", team=self.team, distinct_id="person_2", properties={"$browser": "Chrome"},
            )
            event3 = Event.objects.create(
                event="event_name", team=self.team, distinct_id="person_2", properties={"$browser": "Safari"},
            )

            cohort = Cohort.objects.create(team=self.team, groups=[{"properties": {"name": "Jane"}}])
            cohort.calculate_people()

            with self.assertNumQueries(1):
                response = trends().run(
                    Filter(
                        data={
                            "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                            "events": [{"id": "event_name"}],
                        }
                    ),
                    self.team,
                )
            self.assertEqual(response[0]["count"], 2)
            self.assertEqual(response[0]["data"][-1], 2)

        def test_date_filtering(self):
            self._create_events()
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(data={"date_from": "2019-12-21", "events": [{"id": "sign up"}]}), self.team
                )
            self.assertEqual(response[0]["labels"][3], "Tue. 24 December")
            self.assertEqual(response[0]["data"][3], 1.0)
            self.assertEqual(response[0]["data"][12], 1.0)

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
            self.assertEqual(response[0]["labels"][6], "Wed. 1 January, 00:06")
            self.assertEqual(response[0]["data"][6], 3.0)

            # test hour
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(data={"date_from": "2019-12-24", "interval": "hour", "events": [{"id": "sign up"}]}),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][3], "Tue. 24 December, 03:00")
            self.assertEqual(response[0]["data"][3], 1.0)
            # 217 - 24 - 1
            self.assertEqual(response[0]["data"][192], 3.0)

            # test week
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(data={"date_from": "2019-11-24", "interval": "week", "events": [{"id": "sign up"}]}),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][4], "Sun. 22 December")
            self.assertEqual(response[0]["data"][4], 1.0)
            self.assertEqual(response[0]["labels"][5], "Sun. 29 December")
            self.assertEqual(response[0]["data"][5], 4.0)

            # test month
            with freeze_time("2020-01-02"):
                response = trends().run(
                    Filter(data={"date_from": "2019-9-24", "interval": "month", "events": [{"id": "sign up"}]}),
                    self.team,
                )
            self.assertEqual(response[0]["labels"][2], "Sat. 30 November")
            self.assertEqual(response[0]["data"][2], 1.0)
            self.assertEqual(response[0]["labels"][3], "Tue. 31 December")
            self.assertEqual(response[0]["data"][3], 4.0)

            with freeze_time("2020-01-02 23:30"):
                Event.objects.create(team=self.team, event="sign up", distinct_id="blabla")

            # test today + hourly
            with freeze_time("2020-01-02T23:31:00Z"):
                response = trends().run(
                    Filter(data={"date_from": "dStart", "interval": "hour", "events": [{"id": "sign up"}]}), self.team
                )
            self.assertEqual(response[0]["labels"][23], "Thu. 2 January, 23:00")
            self.assertEqual(response[0]["data"][23], 1.0)

        def test_all_dates_filtering(self):
            self._create_events(use_time=True)
            # automatically sets first day as first day of any events
            with freeze_time("2020-01-04T15:01:01Z"):
                response = trends().run(Filter(data={"date_from": "all", "events": [{"id": "sign up"}]}), self.team)
            self.assertEqual(response[0]["labels"][0], "Tue. 24 December")
            self.assertEqual(response[0]["data"][0], 1.0)

            # test empty response
            with freeze_time("2020-01-04"):
                empty = trends().run(
                    Filter(data={"date_from": "all", "events": [{"id": "blabla"}, {"id": "sign up"}]}), self.team
                )
            self.assertEqual(empty[0]["data"][0], 0)

        def test_breakdown_filtering(self):
            self._create_events()
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
            self.assertEqual(response[0]["breakdown_value"], "None")

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
            self.assertEqual(response[1]["label"], "sign up - 80.0")
            self.assertEqual(response[1]["count"], 1.0)

        def test_breakdown_filtering_limit(self):
            self._create_breakdown_events()
            with freeze_time("2020-01-04T13:01:01Z"):
                response = trends().run(
                    Filter(
                        data={
                            "date_from": "-14d",
                            "breakdown": "$some_property",
                            "events": [{"id": "sign up", "name": "sign up", "type": "events", "order": 0,}],
                        }
                    ),
                    self.team,
                )
            self.assertEqual(len(response), 20)

        def test_action_filtering(self):
            sign_up_action, person = self._create_events()
            action_response = trends().run(Filter(data={"actions": [{"id": sign_up_action.id}]}), self.team)
            event_response = trends().run(Filter(data={"events": [{"id": "sign up"}]}), self.team)
            self.assertEqual(len(action_response), 1)

            self.assertTrue(self._compare_entity_response(action_response, event_response))

        def test_trends_for_non_existing_action(self):
            with freeze_time("2020-01-04"):
                response = trends().run(Filter(data={"actions": [{"id": 50000000}]}), self.team)
            self.assertEqual(len(response), 0)

            with freeze_time("2020-01-04"):
                response = trends().run(Filter(data={"events": [{"id": "DNE"}]}), self.team)
            self.assertEqual(response[0]["data"], [0, 0, 0, 0, 0, 0, 0, 0])

        def test_dau_filtering(self):
            sign_up_action, person = self._create_events()
            with freeze_time("2020-01-02"):
                Person.objects.create(team=self.team, distinct_ids=["someone_else"])
                Event.objects.create(team=self.team, event="sign up", distinct_id="someone_else")
            with freeze_time("2020-01-04"):
                action_response = trends().run(
                    Filter(data={"actions": [{"id": sign_up_action.id, "math": "dau"}]}), self.team
                )
                response = trends().run(Filter(data={"events": [{"id": "sign up", "math": "dau"}]}), self.team)

            self.assertEqual(response[0]["data"][4], 1)
            self.assertEqual(response[0]["data"][5], 2)

            self.assertTrue(self._compare_entity_response(action_response, response))

        def test_dau_with_breakdown_filtering(self):
            sign_up_action, _ = self._create_events()
            with freeze_time("2020-01-02"):
                Event.objects.create(
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

            self.assertTrue(self._compare_entity_response(action_response, event_response))

        def _create_maths_events(self):
            sign_up_action, person = self._create_events()
            Person.objects.create(team=self.team, distinct_ids=["someone_else"])
            Event.objects.create(
                team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": 2}
            )
            Event.objects.create(
                team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": 3}
            )
            Event.objects.create(
                team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": 5}
            )
            Event.objects.create(
                team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": 8}
            )
            return sign_up_action

        def test_sum_filtering(self):
            sign_up_action = self._create_maths_events()

            action_response = trends().run(
                Filter(data={"actions": [{"id": sign_up_action.id, "math": "sum", "math_property": "some_number"}]}),
                self.team,
            )
            event_response = trends().run(
                Filter(data={"events": [{"id": "sign up", "math": "sum", "math_property": "some_number"}]}), self.team
            )
            self.assertEqual(action_response[0]["data"][-1], 18)
            self.assertTrue(self._compare_entity_response(action_response, event_response))

        def test_avg_filtering(self):
            sign_up_action = self._create_maths_events()

            action_response = trends().run(
                Filter(data={"actions": [{"id": sign_up_action.id, "math": "avg", "math_property": "some_number"}]}),
                self.team,
            )
            event_response = trends().run(
                Filter(data={"events": [{"id": "sign up", "math": "avg", "math_property": "some_number"}]}), self.team
            )
            self.assertEqual(action_response[0]["data"][-1], 4.5)
            self.assertTrue(self._compare_entity_response(action_response, event_response))

        def test_min_filtering(self):
            sign_up_action = self._create_maths_events()
            action_response = trends().run(
                Filter(data={"actions": [{"id": sign_up_action.id, "math": "min", "math_property": "some_number"}]}),
                self.team,
            )
            event_response = trends().run(
                Filter(data={"events": [{"id": "sign up", "math": "min", "math_property": "some_number"}]}), self.team
            )
            self.assertEqual(action_response[0]["data"][-1], 2)
            self.assertTrue(self._compare_entity_response(action_response, event_response))

        def test_max_filtering(self):
            sign_up_action = self._create_maths_events()
            action_response = trends().run(
                Filter(data={"actions": [{"id": sign_up_action.id, "math": "max", "math_property": "some_number"}]}),
                self.team,
            )
            event_response = trends().run(
                Filter(data={"events": [{"id": "sign up", "math": "max", "math_property": "some_number"}]}), self.team
            )
            self.assertEqual(action_response[0]["data"][-1], 8)
            self.assertTrue(self._compare_entity_response(action_response, event_response))

        def test_avg_filtering_non_number_resiliency(self):
            sign_up_action, person = self._create_events()
            Person.objects.create(team=self.team, distinct_ids=["someone_else"])
            Event.objects.create(
                team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": 2}
            )
            Event.objects.create(
                team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": "x"}
            )
            Event.objects.create(
                team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": None}
            )
            Event.objects.create(
                team=self.team, event="sign up", distinct_id="someone_else", properties={"some_number": 8}
            )
            action_response = trends().run(
                Filter(data={"actions": [{"id": sign_up_action.id, "math": "avg", "math_property": "some_number"}]}),
                self.team,
            )
            event_response = trends().run(
                Filter(data={"events": [{"id": "sign up", "math": "avg", "math_property": "some_number"}]}), self.team
            )
            self.assertEqual(action_response[0]["data"][-1], 5)
            self.assertTrue(self._compare_entity_response(action_response, event_response))

        def _create_multiple_people(self):
            person1 = Person.objects.create(team=self.team, distinct_ids=["person1"], properties={"name": "person1"})
            Event.objects.create(
                team=self.team, event="watched movie", distinct_id="person1", timestamp="2020-01-01T12:00:00Z",
            )

            person2 = Person.objects.create(team=self.team, distinct_ids=["person2"], properties={"name": "person2"})
            Event.objects.create(
                team=self.team, event="watched movie", distinct_id="person2", timestamp="2020-01-01T12:00:00Z",
            )
            Event.objects.create(
                team=self.team, event="watched movie", distinct_id="person2", timestamp="2020-01-02T12:00:00Z",
            )
            # same day
            Event.objects.create(
                team=self.team, event="watched movie", distinct_id="person2", timestamp="2020-01-02T12:00:00Z",
            )

            person3 = Person.objects.create(team=self.team, distinct_ids=["person3"], properties={"name": "person3"})
            Event.objects.create(
                team=self.team, event="watched movie", distinct_id="person3", timestamp="2020-01-01T12:00:00Z",
            )
            Event.objects.create(
                team=self.team, event="watched movie", distinct_id="person3", timestamp="2020-01-02T12:00:00Z",
            )
            Event.objects.create(
                team=self.team, event="watched movie", distinct_id="person3", timestamp="2020-01-03T12:00:00Z",
            )

            person4 = Person.objects.create(team=self.team, distinct_ids=["person4"], properties={"name": "person4"})
            Event.objects.create(
                team=self.team, event="watched movie", distinct_id="person4", timestamp="2020-01-05T12:00:00Z",
            )
            return (person1, person2, person3, person4)

        def test_breakdown_by_cohort(self):
            person1, person2, person3, person4 = self._create_multiple_people()
            cohort = Cohort.objects.create(name="cohort1", team=self.team, groups=[{"properties": {"name": "person1"}}])
            cohort2 = Cohort.objects.create(
                name="cohort2", team=self.team, groups=[{"properties": {"name": "person2"}}]
            )
            cohort3 = Cohort.objects.create(
                name="cohort3",
                team=self.team,
                groups=[{"properties": {"name": "person1"}}, {"properties": {"name": "person2"}},],
            )
            cohort.calculate_people()
            cohort2.calculate_people()
            cohort3.calculate_people()
            action = Action.objects.create(name="watched movie", team=self.team)
            ActionStep.objects.create(action=action, event="watched movie")
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

            self.assertEqual(event_response[1]["label"], "watched movie - cohort2")
            self.assertEqual(event_response[2]["label"], "watched movie - cohort3")
            self.assertEqual(event_response[3]["label"], "watched movie - all users")

            self.assertEqual(sum(event_response[0]["data"]), 1)
            self.assertEqual(event_response[0]["breakdown_value"], cohort.pk)

            self.assertEqual(sum(event_response[1]["data"]), 3)
            self.assertEqual(event_response[1]["breakdown_value"], cohort2.pk)

            self.assertEqual(sum(event_response[2]["data"]), 4)
            self.assertEqual(event_response[2]["breakdown_value"], cohort3.pk)

            self.assertEqual(sum(event_response[3]["data"]), 7)
            self.assertEqual(event_response[3]["breakdown_value"], "all")

            self.assertTrue(self._compare_entity_response(event_response, action_response,))

        def test_breakdown_by_person_property(self):
            person1, person2, person3, person4 = self._create_multiple_people()
            action = Action.objects.create(name="watched movie", team=self.team)
            ActionStep.objects.create(action=action, event="watched movie")
            action.calculate_events()

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

            self.assertEqual(event_response[0]["count"], 3)
            self.assertEqual(event_response[0]["breakdown_value"], "person2")

            self.assertEqual(event_response[1]["count"], 1)
            self.assertEqual(event_response[1]["breakdown_value"], "person1")

            self.assertEqual(event_response[2]["count"], 3)
            self.assertEqual(event_response[2]["breakdown_value"], "person3")

            self.assertEqual(event_response[3]["count"], 0)
            self.assertEqual(event_response[3]["breakdown_value"], "person4")

            self.assertTrue(self._compare_entity_response(event_response, action_response,))

    return TestTrends


class DjangoTrends(trend_test_factory(Trends)):
    pass
