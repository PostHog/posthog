import json

from freezegun import freeze_time

from posthog.constants import ENTITY_ID, ENTITY_MATH, ENTITY_TYPE
from posthog.models import Action, ActionStep, Cohort, Event, Organization, Person
from posthog.queries.abstract_test.test_interval import AbstractIntervalTest
from posthog.tasks.calculate_action import calculate_actions_from_last_calculation
from posthog.test.base import APIBaseTest


def action_people_test_factory(event_factory, person_factory, action_factory, cohort_factory):
    class TestActionPeople(AbstractIntervalTest, APIBaseTest):
        def _create_events(self, use_time=False):
            action_factory(team=self.team, name="no events")

            sign_up_action = action_factory(team=self.team, name="sign up")

            person = person_factory(team_id=self.team.pk, distinct_ids=["blabla", "anonymous_id"])
            secondTeam = Organization.objects.bootstrap(None, team_fields={"api_token": "token456"})[2]

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
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$some_property": "value"},
                )

            with freeze_time(freeze_args[1]):
                event_factory(
                    team=self.team, event="sign up", distinct_id="blabla", properties={"$some_property": "value"},
                )
                event_factory(team=self.team, event="sign up", distinct_id="anonymous_id")
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
            return sign_up_action, person

        def _create_breakdown_events(self):
            freeze_without_time = ["2020-01-02"]

            action_factory(team=self.team, name="sign up")

            with freeze_time(freeze_without_time[0]):
                for i in range(25):
                    event_factory(
                        team=self.team, event="sign up", distinct_id="blabla", properties={"$some_property": i},
                    )

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

        def test_people_endpoint_paginated(self):

            for index in range(0, 150):
                person_factory(team_id=self.team.pk, distinct_ids=["person" + str(index)])
                event_factory(
                    team=self.team,
                    event="sign up",
                    distinct_id="person" + str(index),
                    timestamp="2020-01-04T12:00:00Z",
                )

            event_response = self.client.get(
                "/api/action/people/",
                data={"date_from": "2020-01-04", "date_to": "2020-01-04", ENTITY_TYPE: "events", ENTITY_ID: "sign up",},
            ).json()

            self.assertEqual(len(event_response["results"][0]["people"]), 100)
            event_response_next = self.client.get(event_response["next"]).json()
            self.assertEqual(len(event_response_next["results"][0]["people"]), 50)

        def _create_people_interval_events(self):
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person1"])
            person2 = person_factory(team_id=self.team.pk, distinct_ids=["person2"])
            person3 = person_factory(team_id=self.team.pk, distinct_ids=["person3"])
            person4 = person_factory(team_id=self.team.pk, distinct_ids=["person4"])
            person5 = person_factory(team_id=self.team.pk, distinct_ids=["person5"])
            person6 = person_factory(team_id=self.team.pk, distinct_ids=["person6"])
            person7 = person_factory(team_id=self.team.pk, distinct_ids=["person7"])

            # solo
            event_factory(
                team=self.team, event="sign up", distinct_id="person1", timestamp="2020-01-04T14:10:00Z",
            )
            # group by hour
            event_factory(
                team=self.team, event="sign up", distinct_id="person2", timestamp="2020-01-04T16:30:00Z",
            )
            # group by hour
            event_factory(
                team=self.team, event="sign up", distinct_id="person3", timestamp="2020-01-04T16:50:00Z",
            )
            # group by min
            event_factory(
                team=self.team, event="sign up", distinct_id="person4", timestamp="2020-01-04T19:20:00Z",
            )
            # group by min
            event_factory(
                team=self.team, event="sign up", distinct_id="person5", timestamp="2020-01-04T19:20:00Z",
            )
            # group by week and month
            event_factory(
                team=self.team, event="sign up", distinct_id="person6", timestamp="2019-11-05T16:30:00Z",
            )
            # group by week and month
            event_factory(
                team=self.team, event="sign up", distinct_id="person7", timestamp="2019-11-07T16:50:00Z",
            )
            event_factory(
                team=self.team, event="sign up", distinct_id="person1", timestamp="2019-11-27T16:50:00Z",
            )
            calculate_actions_from_last_calculation()
            return person1, person2, person3, person4, person5, person6, person7

        def test_minute_interval(self):
            sign_up_action, person = self._create_events()

            person1, person2, person3, person4, person5, person6, person7 = self._create_people_interval_events()

            # check grouped minute
            min_grouped_action_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "minute",
                    "date_from": "2020-01-04 19:20:00",
                    "date_to": "2020-01-04 19:20:00",
                    ENTITY_TYPE: "actions",
                    ENTITY_ID: sign_up_action.id,
                },
            ).json()
            min_grouped_grevent_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "minute",
                    "date_from": "2020-01-04 19:20:00",
                    "date_to": "2020-01-04 19:20:00",
                    ENTITY_TYPE: "events",
                    ENTITY_ID: "sign up",
                },
            ).json()

            all_people_ids = [str(person["id"]) for person in min_grouped_action_response["results"][0]["people"]]
            self.assertListEqual(sorted(all_people_ids), sorted([str(person4.pk), str(person5.pk)]))
            self.assertEqual(len(all_people_ids), 2)
            self.assertEntityResponseEqual(
                min_grouped_action_response["results"], min_grouped_grevent_response["results"], remove=[],
            )

        def test_hour_interval(self):
            sign_up_action, person = self._create_events()

            person1, person2, person3, person4, person5, person6, person7 = self._create_people_interval_events()

            # check solo hour
            action_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "hour",
                    "date_from": "2020-01-04 14:00:00",
                    "date_to": "2020-01-04 14:00:00",
                    ENTITY_TYPE: "actions",
                    ENTITY_ID: sign_up_action.id,
                },
            ).json()
            event_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "hour",
                    "date_from": "2020-01-04 14:00:00",
                    "date_to": "2020-01-04 14:00:00",
                    ENTITY_TYPE: "events",
                    ENTITY_ID: "sign up",
                },
            ).json()
            self.assertEqual(str(action_response["results"][0]["people"][0]["id"]), str(person1.pk))
            self.assertEqual(len(action_response["results"][0]["people"]), 1)
            self.assertEntityResponseEqual(action_response["results"], event_response["results"], remove=[])

            # check grouped hour
            hour_grouped_action_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "hour",
                    "date_from": "2020-01-04 16:00:00",
                    "date_to": "2020-01-04 16:00:00",
                    ENTITY_TYPE: "actions",
                    ENTITY_ID: sign_up_action.id,
                },
            ).json()
            hour_grouped_grevent_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "hour",
                    "date_from": "2020-01-04 16:00:00",
                    "date_to": "2020-01-04 16:00:00",
                    ENTITY_TYPE: "events",
                    ENTITY_ID: "sign up",
                },
            ).json()
            all_people_ids = [str(person["id"]) for person in hour_grouped_action_response["results"][0]["people"]]
            self.assertListEqual(sorted(all_people_ids), sorted([str(person2.pk), str(person3.pk)]))
            self.assertEqual(len(all_people_ids), 2)
            self.assertEntityResponseEqual(
                hour_grouped_action_response["results"], hour_grouped_grevent_response["results"], remove=[],
            )

        def test_day_interval(self):
            sign_up_action, person = self._create_events()
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person1"])
            person_factory(team_id=self.team.pk, distinct_ids=["person2"])
            event_factory(
                team=self.team, event="sign up", distinct_id="person1", timestamp="2020-01-04T12:00:00Z",
            )
            event_factory(
                team=self.team, event="sign up", distinct_id="person2", timestamp="2020-01-05T12:00:00Z",
            )
            calculate_actions_from_last_calculation()
            # test people
            action_response = self.client.get(
                "/api/action/people/",
                data={
                    "date_from": "2020-01-04",
                    "date_to": "2020-01-04",
                    ENTITY_TYPE: "actions",
                    "interval": "day",
                    ENTITY_ID: sign_up_action.id,
                },
            ).json()
            event_response = self.client.get(
                "/api/action/people/",
                data={
                    "date_from": "2020-01-04",
                    "date_to": "2020-01-04",
                    ENTITY_TYPE: "events",
                    ENTITY_ID: "sign up",
                    "interval": "day",
                },
            ).json()

            self.assertEqual(str(action_response["results"][0]["people"][0]["id"]), str(person1.pk))
            self.assertEntityResponseEqual(action_response["results"], event_response["results"], remove=[])

        def test_week_interval(self):
            sign_up_action, person = self._create_events()

            person1, person2, person3, person4, person5, person6, person7 = self._create_people_interval_events()

            # check grouped week
            week_grouped_action_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "week",
                    "date_from": "2019-11-01",
                    "date_to": "2019-11-01",
                    ENTITY_TYPE: "actions",
                    ENTITY_ID: sign_up_action.id,
                },
            ).json()
            week_grouped_grevent_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "week",
                    "date_from": "2019-11-01",
                    "date_to": "2019-11-01",
                    ENTITY_TYPE: "events",
                    ENTITY_ID: "sign up",
                },
            ).json()

            all_people_ids = [str(person["id"]) for person in week_grouped_action_response["results"][0]["people"]]
            self.assertListEqual(sorted(all_people_ids), sorted([str(person6.pk), str(person7.pk)]))
            self.assertEqual(len(all_people_ids), 2)

            self.assertEntityResponseEqual(
                week_grouped_action_response["results"], week_grouped_grevent_response["results"], remove=[],
            )

        def test_month_interval(self):
            sign_up_action, person = self._create_events()

            person1, person2, person3, person4, person5, person6, person7 = self._create_people_interval_events()

            # check grouped month
            month_group_action_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "month",
                    "date_from": "2019-11-01",
                    "date_to": "2019-11-01",
                    ENTITY_TYPE: "actions",
                    ENTITY_ID: sign_up_action.id,
                },
            ).json()
            month_group_grevent_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "month",
                    "date_from": "2019-11-01",
                    "date_to": "2019-11-01",
                    ENTITY_TYPE: "events",
                    ENTITY_ID: "sign up",
                },
            ).json()

            all_people_ids = [str(person["id"]) for person in month_group_action_response["results"][0]["people"]]
            self.assertListEqual(sorted(all_people_ids), sorted([str(person6.pk), str(person7.pk), str(person1.pk)]))
            self.assertEqual(len(all_people_ids), 3)

            self.assertEntityResponseEqual(
                month_group_action_response["results"], month_group_grevent_response["results"], remove=[],
            )

        def test_interval_rounding(self):
            pass

        def _create_multiple_people(self):
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person1"], properties={"name": "person1"})
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person1",
                timestamp="2020-01-01T12:00:00Z",
                properties={"event_prop": "prop1"},
            )

            person2 = person_factory(team_id=self.team.pk, distinct_ids=["person2"], properties={"name": "person2"})
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person2",
                timestamp="2020-01-01T12:00:00Z",
                properties={"event_prop": "prop1"},
            )
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person2",
                timestamp="2020-01-02T12:00:00Z",
                properties={"event_prop": "prop1"},
            )
            # same day
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person2",
                timestamp="2020-01-02T12:00:00Z",
                properties={"event_prop": "prop1"},
            )

            person3 = person_factory(team_id=self.team.pk, distinct_ids=["person3"], properties={"name": "person3"})
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person3",
                timestamp="2020-01-01T12:00:00Z",
                properties={"event_prop": "prop2"},
            )
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person3",
                timestamp="2020-01-02T12:00:00Z",
                properties={"event_prop": "prop2"},
            )
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person3",
                timestamp="2020-01-03T12:00:00Z",
                properties={"event_prop": "prop2"},
            )

            person4 = person_factory(team_id=self.team.pk, distinct_ids=["person4"], properties={"name": "person4"})
            event_factory(
                team=self.team,
                event="watched movie",
                distinct_id="person4",
                timestamp="2020-01-05T12:00:00Z",
                properties={"event_prop": "prop3"},
            )
            return (person1, person2, person3, person4)

        def test_people_csv(self):
            person1, _, _, _ = self._create_multiple_people()
            people = self.client.get(
                "/api/action/people.csv",
                data={
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                    ENTITY_TYPE: "events",
                    ENTITY_ID: "watched movie",
                    "display": "ActionsLineGraphCumulative",
                    "entity_math": "dau",
                    "events": [{"id": "watched movie", "math": "dau"}],
                },
            )
            resp = people.content.decode("utf-8").split("\r\n")
            resp = sorted(resp)
            self.assertEqual(len(resp), 6)  # header, 4 people, empty line
            self.assertEqual(resp[1], "Distinct ID,Internal ID,Email,Name,Properties")
            self.assertEqual(resp[2].split(",")[0], "person1")

        def test_breakdown_by_cohort_people_endpoint(self):
            person1, _, _, _ = self._create_multiple_people()
            cohort = cohort_factory(name="cohort1", team=self.team, groups=[{"properties": {"name": "person1"}}])
            cohort_factory(name="cohort2", team=self.team, groups=[{"properties": {"name": "person2"}}])
            cohort_factory(
                name="cohort3",
                team=self.team,
                groups=[{"properties": {"name": "person1"}}, {"properties": {"name": "person2"}},],
            )
            action_factory(name="watched movie", team=self.team)

            people = self.client.get(
                "/api/action/people/",
                data={
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                    ENTITY_TYPE: "events",
                    ENTITY_ID: "watched movie",
                    "breakdown_type": "cohort",
                    "breakdown_value": cohort.pk,
                    "breakdown": [cohort.pk],  # this shouldn't do anything
                },
            ).json()

            self.assertEqual(len(people["results"][0]["people"]), 1)
            ordered_people = sorted(people["results"][0]["people"], key=lambda i: i["id"])
            self.assertEqual(ordered_people[0]["id"], person1.pk)

            # all people
            people = self.client.get(
                "/api/action/people/",
                data={
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                    ENTITY_TYPE: "events",
                    ENTITY_ID: "watched movie",
                    "breakdown_type": "cohort",
                    "breakdown_value": "all",
                    "breakdown": [cohort.pk],
                },
            ).json()

            self.assertEqual(len(people["results"][0]["people"]), 4)
            ordered_people = sorted(people["results"][0]["people"], key=lambda i: i["id"])
            self.assertEqual(ordered_people[0]["id"], person1.pk)

        def test_breakdown_by_person_property_people_endpoint(self):
            person1, person2, person3, person4 = self._create_multiple_people()
            action = action_factory(name="watched movie", team=self.team)

            people = self.client.get(
                "/api/action/people/",
                data={
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                    ENTITY_TYPE: "events",
                    ENTITY_ID: "watched movie",
                    "breakdown_type": "person",
                    "breakdown_value": "person3",
                    "breakdown": "name",
                },
            ).json()
            self.assertEqual(len(people["results"][0]["people"]), 1)
            self.assertEqual(people["results"][0]["people"][0]["id"], person3.pk)

        def test_breakdown_by_event_property_people_endpoint(self):
            person1, person2, person3, person4 = self._create_multiple_people()
            action = action_factory(name="watched movie", team=self.team)

            people = self.client.get(
                "/api/action/people/",
                data={
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                    ENTITY_TYPE: "events",
                    ENTITY_ID: "watched movie",
                    "breakdown_type": "event",
                    "breakdown_value": "prop1",
                    "breakdown": "event_prop",
                },
            ).json()

            self.assertEqual(len(people["results"][0]["people"]), 2)
            ordered_people = sorted([p["id"] for p in people["results"][0]["people"]])
            self.assertEqual(ordered_people, sorted([person1.pk, person2.pk]))

        def test_filtering_by_person_properties(self):
            person1, person2, person3, person4 = self._create_multiple_people()

            people = self.client.get(
                "/api/action/people/",
                data={
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                    ENTITY_TYPE: "events",
                    ENTITY_ID: "watched movie",
                    "properties": json.dumps([{"key": "name", "value": "person2", "type": "person"}]),
                },
            ).json()

            self.assertEqual(len(people["results"][0]["people"]), 1)
            self.assertEqual(people["results"][0]["people"][0]["id"], person2.pk)

    return TestActionPeople


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


class TestActionPeople(action_people_test_factory(Event.objects.create, Person.objects.create, _create_action, _create_cohort)):  # type: ignore
    pass
