from json import dumps as jdumps

from freezegun import freeze_time

from posthog.models import Action, ActionStep, Cohort, Event, Person, Team

from .base import TransactionBaseTest


def action_people_test_factory(event_factory, person_factory, action_factory, cohort_factory):
    class TestActionPeople(TransactionBaseTest):
        TESTS_API = True

        def _create_events(self, use_time=False):
            no_events = action_factory(team=self.team, name="no events")

            sign_up_action = action_factory(team=self.team, name="sign up")

            person = person_factory(team_id=self.team.pk, distinct_ids=["blabla", "anonymous_id"])
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

            sign_up_action = action_factory(team=self.team, name="sign up")

            with freeze_time(freeze_without_time[0]):
                for i in range(25):
                    event_factory(
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

        def test_people_endpoint(self):
            sign_up_action, person = self._create_events()
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person1"])
            person_factory(team_id=self.team.pk, distinct_ids=["person2"])
            event_factory(
                team=self.team, event="sign up", distinct_id="person1", timestamp="2020-01-04T12:00:00Z",
            )
            event_factory(
                team=self.team, event="sign up", distinct_id="person2", timestamp="2020-01-05T12:00:00Z",
            )
            # test people
            action_response = self.client.get(
                "/api/action/people/",
                data={
                    "date_from": "2020-01-04",
                    "date_to": "2020-01-04",
                    "type": "actions",
                    "entityId": sign_up_action.id,
                },
            ).json()
            event_response = self.client.get(
                "/api/action/people/",
                data={"date_from": "2020-01-04", "date_to": "2020-01-04", "type": "events", "entityId": "sign up",},
            ).json()

            self.assertEqual(action_response["results"][0]["people"][0]["id"], person1)
            self.assertTrue(
                self._compare_entity_response(action_response["results"], event_response["results"], remove=[])
            )

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
                data={"date_from": "2020-01-04", "date_to": "2020-01-04", "type": "events", "entityId": "sign up",},
            ).json()

            self.assertEqual(len(event_response["results"][0]["people"]), 100)
            event_response_next = self.client.get(event_response["next"]).json()
            self.assertEqual(len(event_response_next["results"][0]["people"]), 50)

        def test_people_endpoint_with_intervals(self):
            sign_up_action, person = self._create_events()

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

            # check solo hour
            action_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "hour",
                    "date_from": "2020-01-04 14:00:00",
                    "date_to": "2020-01-04 15:00:00",
                    "type": "actions",
                    "entityId": sign_up_action.id,
                },
            ).json()
            event_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "hour",
                    "date_from": "2020-01-04 14:00:00",
                    "date_to": "2020-01-04 15:00:00",
                    "type": "events",
                    "entityId": "sign up",
                },
            ).json()

            self.assertEqual(action_response["results"][0]["people"][0]["id"], person1)
            self.assertEqual(len(action_response["results"][0]["people"]), 1)
            self.assertTrue(
                self._compare_entity_response(action_response["results"], event_response["results"], remove=[])
            )

            # check grouped hour
            hour_grouped_action_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "hour",
                    "date_from": "2020-01-04 16:00:00",
                    "date_to": "2020-01-04 17:00:00",
                    "type": "actions",
                    "entityId": sign_up_action.id,
                },
            ).json()
            hour_grouped_grevent_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "hour",
                    "date_from": "2020-01-04 16:00:00",
                    "date_to": "2020-01-04 17:00:00",
                    "type": "events",
                    "entityId": "sign up",
                },
            ).json()
            all_people_ids = [person["id"] for person in hour_grouped_action_response["results"][0]["people"]]
            self.assertListEqual(sorted(all_people_ids), sorted([person2, person3]))
            self.assertEqual(len(all_people_ids), 2)
            self.assertTrue(
                self._compare_entity_response(
                    hour_grouped_action_response["results"], hour_grouped_grevent_response["results"], remove=[],
                )
            )

            # check grouped minute
            min_grouped_action_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "hour",
                    "date_from": "2020-01-04 19:20:00",
                    "date_to": "2020-01-04 19:20:00",
                    "type": "actions",
                    "entityId": sign_up_action.id,
                },
            ).json()
            min_grouped_grevent_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "hour",
                    "date_from": "2020-01-04 19:20:00",
                    "date_to": "2020-01-04 19:20:00",
                    "type": "events",
                    "entityId": "sign up",
                },
            ).json()

            all_people_ids = [person["id"] for person in min_grouped_action_response["results"][0]["people"]]
            self.assertListEqual(sorted(all_people_ids), sorted([person4, person5]))
            self.assertEqual(len(all_people_ids), 2)
            self.assertTrue(
                self._compare_entity_response(
                    min_grouped_action_response["results"], min_grouped_grevent_response["results"], remove=[],
                )
            )

            # check grouped week
            week_grouped_action_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "week",
                    "date_from": "2019-11-01",
                    "date_to": "2019-11-08",
                    "type": "actions",
                    "entityId": sign_up_action.id,
                },
            ).json()
            week_grouped_grevent_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "week",
                    "date_from": "2019-11-01",
                    "date_to": "2019-11-08",
                    "type": "events",
                    "entityId": "sign up",
                },
            ).json()

            all_people_ids = [person["id"] for person in week_grouped_action_response["results"][0]["people"]]
            self.assertListEqual(sorted(all_people_ids), sorted([person6, person7]))
            self.assertEqual(len(all_people_ids), 2)

            self.assertTrue(
                self._compare_entity_response(
                    week_grouped_action_response["results"], week_grouped_grevent_response["results"], remove=[],
                )
            )

            # check grouped month
            month_group_action_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "month",
                    "date_from": "2019-11-01",
                    "date_to": "2019-12-01",
                    "type": "actions",
                    "entityId": sign_up_action.id,
                },
            ).json()
            month_group_grevent_response = self.client.get(
                "/api/action/people/",
                data={
                    "interval": "month",
                    "date_from": "2019-11-01",
                    "date_to": "2019-12-01",
                    "type": "events",
                    "entityId": "sign up",
                },
            ).json()

            all_people_ids = [person["id"] for person in month_group_action_response["results"][0]["people"]]
            self.assertListEqual(sorted(all_people_ids), sorted([person6, person7]))
            self.assertEqual(len(all_people_ids), 2)

            self.assertTrue(
                self._compare_entity_response(
                    month_group_action_response["results"], month_group_grevent_response["results"], remove=[],
                )
            )

        def _create_multiple_people(self):
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["person1"], properties={"name": "person1"})
            event_factory(
                team=self.team, event="watched movie", distinct_id="person1", timestamp="2020-01-01T12:00:00Z",
            )

            person2 = person_factory(team_id=self.team.pk, distinct_ids=["person2"], properties={"name": "person2"})
            event_factory(
                team=self.team, event="watched movie", distinct_id="person2", timestamp="2020-01-01T12:00:00Z",
            )
            event_factory(
                team=self.team, event="watched movie", distinct_id="person2", timestamp="2020-01-02T12:00:00Z",
            )
            # same day
            event_factory(
                team=self.team, event="watched movie", distinct_id="person2", timestamp="2020-01-02T12:00:00Z",
            )

            person3 = person_factory(team_id=self.team.pk, distinct_ids=["person3"], properties={"name": "person3"})
            event_factory(
                team=self.team, event="watched movie", distinct_id="person3", timestamp="2020-01-01T12:00:00Z",
            )
            event_factory(
                team=self.team, event="watched movie", distinct_id="person3", timestamp="2020-01-02T12:00:00Z",
            )
            event_factory(
                team=self.team, event="watched movie", distinct_id="person3", timestamp="2020-01-03T12:00:00Z",
            )

            person4 = person_factory(team_id=self.team.pk, distinct_ids=["person4"], properties={"name": "person4"})
            event_factory(
                team=self.team, event="watched movie", distinct_id="person4", timestamp="2020-01-05T12:00:00Z",
            )
            return (person1, person2, person3, person4)

        def test_stickiness_people_endpoint(self):
            person1, _, _, person4 = self._create_multiple_people()

            watched_movie = action_factory(team=self.team, name="watched movie")

            # test people
            action_response = self.client.get(
                "/api/action/people/",
                data={
                    "shown_as": "Stickiness",
                    "stickiness_days": 1,
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                    "type": "actions",
                    "entityId": watched_movie.id,
                },
            ).json()
            event_response = self.client.get(
                "/api/action/people/",
                data={
                    "shown_as": "Stickiness",
                    "stickiness_days": 1,
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-07",
                    "type": "events",
                    "entityId": "watched movie",
                },
            ).json()

            all_people_ids = [person["id"] for person in action_response["results"][0]["people"]]
            self.assertListEqual(sorted(all_people_ids), sorted([person1, person4]))

            self.assertTrue(
                self._compare_entity_response(action_response["results"], event_response["results"], remove=[])
            )

        # def test_breakdown_by_cohort_people_endpoint(self):
        #     person1, person2, person3, person4 = self._create_multiple_people()
        #     cohort = cohort_factory(name="cohort1", team=self.team, groups=[{"properties": {"name": "person1"}}])
        #     cohort2 = cohort_factory(name="cohort2", team=self.team, groups=[{"properties": {"name": "person2"}}])
        #     cohort3 = cohort_factory(
        #         name="cohort3",
        #         team=self.team,
        #         groups=[{"properties": {"name": "person1"}}, {"properties": {"name": "person2"}},],
        #     )
        #     action = action_factory(name="watched movie", team=self.team)

        #     people = self.client.get(
        #         "/api/action/people/",
        #         data={
        #             "date_from": "2020-01-01",
        #             "date_to": "2020-01-07",
        #             "type": "events",
        #             "entityId": "watched movie",
        #             "breakdown_type": "cohort",
        #             "breakdown_value": cohort.pk,
        #             "breakdown": [cohort.pk],  # this shouldn't do anything
        #         },
        #     ).json()

        #     self.assertEqual(len(people["results"][0]["people"]), 1)
        #     ordered_people = sorted(people["results"][0]["people"], key= lambda i: i['id'])
        #     self.assertEqual(ordered_people[0]["id"], person1)

        #     # all people
        #     people = self.client.get(
        #         "/api/action/people/",
        #         data={
        #             "date_from": "2020-01-01",
        #             "date_to": "2020-01-07",
        #             "type": "events",
        #             "entityId": "watched movie",
        #             "breakdown_type": "cohort",
        #             "breakdown_value": "all",
        #             "breakdown": [cohort.pk],
        #         },
        #     ).json()

        #     self.assertEqual(len(people["results"][0]["people"]), 4)
        #     ordered_people = sorted(people["results"][0]["people"], key= lambda i: i['id'])
        #     self.assertEqual(ordered_people[0]["id"], person1)

        # def test_breakdown_by_person_property_people_endpoint(self):
        #     person1, person2, person3, person4 = self._create_multiple_people()
        #     action = action_factory(name="watched movie", team=self.team)

        #     people = self.client.get(
        #         "/api/action/people/",
        #         data={
        #             "date_from": "2020-01-01",
        #             "date_to": "2020-01-07",
        #             "type": "events",
        #             "entityId": "watched movie",
        #             "breakdown_type": "person",
        #             "breakdown_value": "person3",
        #             "breakdown": "name",
        #         },
        #     ).json()
        #     self.assertEqual(len(people["results"][0]["people"]), 1)
        #     self.assertEqual(people["results"][0]["people"][0]["name"], "person3")

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


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return person.pk


class TestActionPeople(action_people_test_factory(Event.objects.create, _create_person, _create_action, _create_cohort)):  # type: ignore
    pass
