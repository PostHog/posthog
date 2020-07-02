from json import dumps as jdumps

from freezegun import freeze_time
from unittest.mock import patch, call
from datetime import datetime

from posthog.models import (
    Action,
    ActionStep,
    Element,
    Event,
    Filter,
    Person,
    Team,
    Cohort,
)
from .base import BaseTest, TransactionBaseTest
from posthog.api.action import calculate_retention


@patch("posthog.tasks.calculate_action.calculate_action.delay")
class TestCreateAction(BaseTest):
    TESTS_API = True

    def test_create_and_update_action(self, patch_delay):
        Event.objects.create(
            team=self.team,
            event="$autocapture",
            elements=[
                Element(tag_name="button", order=0, text="sign up NOW"),
                Element(tag_name="div", order=1),
            ],
        )
        response = self.client.post(
            "/api/action/",
            data={
                "name": "user signed up",
                "steps": [
                    {
                        "text": "sign up",
                        "selector": "div > button",
                        "url": "/signup",
                        "isNew": "asdf",
                    }
                ],
            },
            content_type="application/json",
            HTTP_ORIGIN="http://testserver",
        ).json()
        action = Action.objects.get()
        self.assertEqual(action.name, "user signed up")
        self.assertEqual(action.team, self.team)
        self.assertEqual(action.steps.get().selector, "div > button")
        self.assertEqual(response["steps"][0]["text"], "sign up")

        # test no actions with same name
        user2 = self._create_user("tim2")
        self.client.force_login(user2)
        response = self.client.post(
            "/api/action/",
            data={"name": "user signed up"},
            content_type="application/json",
            HTTP_ORIGIN="http://testserver",
        ).json()
        self.assertEqual(response["detail"], "action-exists")

        # test update
        event2 = Event.objects.create(
            team=self.team,
            event="$autocapture",
            properties={"$browser": "Chrome"},
            elements=[
                Element(tag_name="button", order=0, text="sign up NOW"),
                Element(tag_name="div", order=1),
            ],
        )
        response = self.client.patch(
            "/api/action/%s/" % action.pk,
            data={
                "name": "user signed up 2",
                "steps": [
                    {
                        "id": action.steps.get().pk,
                        "isNew": "asdf",
                        "text": "sign up NOW",
                        "selector": "div > button",
                        "properties": [{"key": "$browser", "value": "Chrome"}],
                        "url": None,
                    },
                    {"href": "/a-new-link"},
                ],
            },
            content_type="application/json",
            HTTP_ORIGIN="http://testserver",
        ).json()
        action = Action.objects.get()
        action.calculate_events()
        steps = action.steps.all().order_by("id")
        self.assertEqual(action.name, "user signed up 2")
        self.assertEqual(steps[0].text, "sign up NOW")
        self.assertEqual(steps[1].href, "/a-new-link")
        self.assertEqual(action.events.get(), event2)
        self.assertEqual(action.events.count(), 1)

        # test queries
        with self.assertNumQueries(5):
            response = self.client.get("/api/action/")

        # test remove steps
        response = self.client.patch(
            "/api/action/%s/" % action.pk,
            data={"name": "user signed up 2", "steps": [],},
            content_type="application/json",
            HTTP_ORIGIN="http://testserver",
        ).json()
        self.assertEqual(ActionStep.objects.count(), 0)

    # When we send a user to their own site, we give them a token.
    # Make sure you can only create actions if that token is set,
    # otherwise evil sites could create actions with a users' session.
    # NOTE: Origin header is only set on cross domain request
    def test_create_from_other_domain(self, patch_delay):
        # FIXME: BaseTest is using Django client to performe calls to a DRF endpoint.
        # Django HttpResponse does not have an attribute `data`. Better use rest_framework.test.APIClient.
        response = self.client.post(
            "/api/action/",
            data={"name": "user signed up",},
            content_type="application/json",
            HTTP_ORIGIN="https://evilwebsite.com",
        )
        self.assertEqual(response.status_code, 403)

        self.user.temporary_token = "token123"
        self.user.save()

        response = self.client.post(
            "/api/action/?temporary_token=token123",
            data={"name": "user signed up",},
            content_type="application/json",
            HTTP_ORIGIN="https://somewebsite.com",
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/api/action/?temporary_token=token123",
            data={"name": "user signed up and post to slack", "post_to_slack": True,},
            content_type="application/json",
            HTTP_ORIGIN="https://somewebsite.com",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["post_to_slack"], True)

        list_response = self.client.get(
            "/api/action/",
            content_type="application/json",
            HTTP_ORIGIN="https://evilwebsite.com",
        )
        self.assertEqual(list_response.status_code, 403)

        detail_response = self.client.get(
            f"/api/action/{response.json()['id']}/",
            content_type="application/json",
            HTTP_ORIGIN="https://evilwebsite.com",
        )
        self.assertEqual(detail_response.status_code, 403)

        self.client.logout()
        list_response = self.client.get(
            "/api/action/",
            data={"temporary_token": "token123",},
            content_type="application/json",
            HTTP_ORIGIN="https://somewebsite.com",
        )
        self.assertEqual(list_response.status_code, 200)

        response = self.client.post(
            "/api/action/?temporary_token=token123",
            data={"name": "user signed up 22",},
            content_type="application/json",
            HTTP_ORIGIN="https://somewebsite.com",
        )
        self.assertEqual(response.status_code, 200, response.json())

    # This case happens when someone is running behind a proxy, but hasn't set `IS_BEHIND_PROXY`
    def test_http_to_https(self, patch_delay):
        response = self.client.post(
            "/api/action/",
            data={"name": "user signed up again",},
            content_type="application/json",
            HTTP_ORIGIN="https://testserver/",
        )
        self.assertEqual(response.status_code, 200, response.json())


class TestTrends(TransactionBaseTest):
    TESTS_API = True

    def _create_events(self, use_time=False):
        no_events = Action.objects.create(team=self.team, name="no events")
        ActionStep.objects.create(action=no_events, event="no events")

        sign_up_action = Action.objects.create(team=self.team, name="sign up")
        ActionStep.objects.create(action=sign_up_action, event="sign up")

        person = Person.objects.create(
            team=self.team, distinct_ids=["blabla", "anonymous_id"]
        )
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
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value"},
            )

        with freeze_time(freeze_args[1]):
            Event.objects.create(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "value"},
            )
            Event.objects.create(
                team=self.team, event="sign up", distinct_id="anonymous_id"
            )
            Event.objects.create(team=self.team, event="sign up", distinct_id="blabla")
        with freeze_time(freeze_args[2]):
            Event.objects.create(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={
                    "$some_property": "other_value",
                    "$some_numerical_prop": 80,
                },
            )
            Event.objects.create(
                team=self.team, event="no events", distinct_id="blabla"
            )

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
                    team=self.team,
                    event="sign up",
                    distinct_id="blabla",
                    properties={"$some_property": i},
                )

    def _compare_entity_response(
        self, response1, response2, remove=("action", "label")
    ):
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
            with self.assertNumQueries(16):
                action_response = self.client.get(
                    "/api/action/trends/?date_from=-7d"
                ).json()
                event_response = self.client.get(
                    "/api/action/trends/",
                    data={
                        "date_from": "-7d",
                        "events": jdumps([{"id": "sign up"}, {"id": "no events"}]),
                    },
                ).json()

        self.assertEqual(action_response[0]["label"], "sign up")
        self.assertEqual(action_response[0]["labels"][4], "Wed. 1 January")
        self.assertEqual(action_response[0]["data"][4], 3.0)
        self.assertEqual(action_response[0]["labels"][5], "Thu. 2 January")
        self.assertEqual(action_response[0]["data"][5], 1.0)
        self.assertEqual(event_response[0]["label"], "sign up")

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_trends_per_day_cumulative(self):
        self._create_events()
        with freeze_time("2020-01-04T13:00:01Z"):
            with self.assertNumQueries(16):
                action_response = self.client.get(
                    "/api/action/trends/?date_from=-7d&display=ActionsLineGraphCumulative"
                ).json()
                event_response = self.client.get(
                    "/api/action/trends/",
                    data={
                        "date_from": "-7d",
                        "events": jdumps([{"id": "sign up"}, {"id": "no events"}]),
                        "display": "ActionsLineGraphCumulative",
                    },
                ).json()

        self.assertEqual(action_response[0]["label"], "sign up")
        self.assertEqual(action_response[0]["labels"][4], "Wed. 1 January")
        self.assertEqual(action_response[0]["data"][4], 3.0)
        self.assertEqual(action_response[0]["labels"][5], "Thu. 2 January")
        self.assertEqual(action_response[0]["data"][5], 4.0)
        self.assertEqual(event_response[0]["label"], "sign up")

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_trends_compare(self):
        self._create_events()
        with freeze_time("2020-01-04T13:00:01Z"):
            action_response = self.client.get(
                "/api/action/trends/?date_from=-7d&compare=true"
            ).json()
            event_response = self.client.get(
                "/api/action/trends/",
                data={
                    "date_from": "-7d",
                    "events": jdumps([{"id": "sign up"}, {"id": "no events"}]),
                    "compare": "true",
                },
            ).json()

        self.assertEqual(action_response[0]["label"], "sign up - current")
        self.assertEqual(action_response[0]["labels"][4], "day 4")
        self.assertEqual(action_response[0]["data"][4], 3.0)
        self.assertEqual(action_response[0]["labels"][5], "day 5")
        self.assertEqual(action_response[0]["data"][5], 1.0)

        self.assertEqual(action_response[1]["label"], "sign up - previous")
        self.assertEqual(action_response[1]["labels"][4], "day 4")
        self.assertEqual(action_response[1]["data"][4], 1.0)
        self.assertEqual(action_response[1]["labels"][5], "day 5")
        self.assertEqual(action_response[1]["data"][5], 0.0)

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_property_filtering(self):
        self._create_events()
        with freeze_time("2020-01-04"):
            action_response = self.client.get(
                "/api/action/trends/",
                data={"properties": jdumps({"$some_property": "value"}),},
            ).json()
            event_response = self.client.get(
                "/api/action/trends/",
                data={
                    "events": jdumps([{"id": "sign up"}, {"id": "no events"}]),
                    "properties": jdumps({"$some_property": "value"}),
                },
            ).json()
        self.assertEqual(action_response[0]["labels"][4], "Wed. 1 January")
        self.assertEqual(action_response[0]["data"][4], 1.0)
        self.assertEqual(action_response[0]["labels"][5], "Thu. 2 January")
        self.assertEqual(action_response[0]["data"][5], 0)
        self.assertEqual(action_response[1]["count"], 0)

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_date_filtering(self):
        self._create_events()
        with freeze_time("2020-01-02"):
            action_response = self.client.get(
                "/api/action/trends/?date_from=2019-12-21"
            ).json()
            event_response = self.client.get(
                "/api/action/trends/",
                data={
                    "date_from": "2019-12-21",
                    "events": jdumps([{"id": "sign up"}, {"id": "no events"}]),
                },
            ).json()
        self.assertEqual(action_response[0]["labels"][3], "Tue. 24 December")
        self.assertEqual(action_response[0]["data"][3], 1.0)
        self.assertEqual(action_response[0]["data"][12], 1.0)

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_interval_filtering(self):
        self._create_events(use_time=True)

        # test minute
        with freeze_time("2020-01-02"):
            action_response = self.client.get(
                "/api/action/trends/?date_from=2020-01-01&interval=minute"
            ).json()
        self.assertEqual(action_response[0]["labels"][6], "Wed. 1 January, 00:06")
        self.assertEqual(action_response[0]["data"][6], 3.0)

        # test hour
        with freeze_time("2020-01-02"):
            action_response = self.client.get(
                "/api/action/trends/?date_from=2019-12-24&interval=hour"
            ).json()
        self.assertEqual(action_response[0]["labels"][3], "Tue. 24 December, 03:00")
        self.assertEqual(action_response[0]["data"][3], 1.0)
        # 217 - 24 - 1
        self.assertEqual(action_response[0]["data"][192], 3.0)

        # test week
        with freeze_time("2020-01-02"):
            action_response = self.client.get(
                "/api/action/trends/?date_from=2019-11-24&interval=week"
            ).json()
        self.assertEqual(action_response[0]["labels"][4], "Sun. 22 December")
        self.assertEqual(action_response[0]["data"][4], 1.0)
        self.assertEqual(action_response[0]["labels"][5], "Sun. 29 December")
        self.assertEqual(action_response[0]["data"][5], 4.0)

        # test month
        with freeze_time("2020-01-02"):
            action_response = self.client.get(
                "/api/action/trends/?date_from=2019-9-24&interval=month"
            ).json()
        self.assertEqual(action_response[0]["labels"][2], "Sat. 30 November")
        self.assertEqual(action_response[0]["data"][2], 1.0)
        self.assertEqual(action_response[0]["labels"][3], "Tue. 31 December")
        self.assertEqual(action_response[0]["data"][3], 4.0)

        with freeze_time("2020-01-02 23:30"):
            Event.objects.create(team=self.team, event="sign up", distinct_id="blabla")

        # test today + hourly
        with freeze_time("2020-01-02T23:31:00Z"):
            action_response = self.client.get(
                "/api/action/trends/",
                data={"date_from": "dStart", "interval": "hour",},
            ).json()
        self.assertEqual(action_response[0]["labels"][23], "Thu. 2 January, 23:00")
        self.assertEqual(action_response[0]["data"][23], 1.0)

    def test_all_dates_filtering(self):
        self._create_events(use_time=True)
        # automatically sets first day as first day of any events
        with freeze_time("2020-01-04T15:01:01Z"):
            action_response = self.client.get(
                "/api/action/trends/?date_from=all"
            ).json()
            event_response = self.client.get(
                "/api/action/trends/",
                data={
                    "date_from": "all",
                    "events": jdumps([{"id": "sign up"}, {"id": "no events"}]),
                },
            ).json()
        self.assertEqual(action_response[0]["labels"][0], "Tue. 24 December")
        self.assertEqual(action_response[0]["data"][0], 1.0)

        self.assertTrue(self._compare_entity_response(action_response, event_response))

        # test empty response
        with freeze_time("2020-01-04"):
            empty = self.client.get(
                "/api/action/trends/?date_from=all&events=%s"
                % jdumps([{"id": "blabla"}, {"id": "sign up"}])
            ).json()
        self.assertEqual(empty[0]["data"][0], 0)

    def test_breakdown_filtering(self):
        self._create_events()
        # test breakdown filtering
        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = self.client.get(
                "/api/action/trends/?date_from=-14d&breakdown=$some_property"
            ).json()
            event_response = self.client.get(
                "/api/action/trends/?date_from=-14d&properties={}&actions=[]&display=ActionsTable&interval=day&breakdown=$some_property&events=%s"
                % jdumps(
                    [
                        {
                            "id": "sign up",
                            "name": "sign up",
                            "type": "events",
                            "order": 0,
                        },
                        {"id": "no events"},
                    ]
                )
            ).json()

        self.assertEqual(event_response[0]["label"], "sign up - Other")
        self.assertEqual(event_response[1]["label"], "sign up - other_value")
        self.assertEqual(event_response[2]["label"], "sign up - value")
        self.assertEqual(event_response[3]["label"], "no events - Other")

        self.assertEqual(sum(event_response[0]["data"]), 2)
        self.assertEqual(event_response[0]["data"][4 + 7], 2)
        self.assertEqual(event_response[0]["breakdown_value"], "None")

        self.assertEqual(sum(event_response[1]["data"]), 1)
        self.assertEqual(event_response[1]["data"][5 + 7], 1)
        self.assertEqual(event_response[1]["breakdown_value"], "other_value")

        self.assertTrue(self._compare_entity_response(action_response, event_response))

        # check numerical breakdown
        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = self.client.get(
                "/api/action/trends/?date_from=-14d&breakdown=$some_numerical_prop"
            ).json()
            event_response = self.client.get(
                "/api/action/trends/?date_from=-14d&properties={}&actions=[]&display=ActionsTable&interval=day&breakdown=$some_numerical_prop&events=%s"
                % jdumps(
                    [
                        {
                            "id": "sign up",
                            "name": "sign up",
                            "type": "events",
                            "order": 0,
                        },
                        {"id": "no events"},
                    ]
                )
            ).json()
        self.assertEqual(event_response[0]["label"], "sign up - Other")
        self.assertEqual(event_response[0]["count"], 4.0)
        self.assertEqual(event_response[1]["label"], "sign up - 80.0")
        self.assertEqual(event_response[1]["count"], 1.0)

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_breakdown_filtering_limit(self):
        self._create_breakdown_events()
        with freeze_time("2020-01-04T13:01:01Z"):
            action_response = self.client.get(
                "/api/action/trends/?date_from=-14d&breakdown=$some_property"
            ).json()
            event_response = self.client.get(
                "/api/action/trends/?date_from=-14d&properties={}&actions=[]&display=ActionsTable&interval=day&breakdown=$some_property&events=%s"
                % jdumps(
                    [{"id": "sign up", "name": "sign up", "type": "events", "order": 0}]
                )
            ).json()
        self.assertEqual(len(action_response), 20)
        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_action_filtering(self):
        sign_up_action, person = self._create_events()
        with freeze_time("2020-01-04"):
            action_response = self.client.get(
                "/api/action/trends/",
                data={"actions": jdumps([{"id": sign_up_action.id}]),},
            ).json()
            event_response = self.client.get(
                "/api/action/trends/", data={"events": jdumps([{"id": "sign up"}]),},
            ).json()
        self.assertEqual(len(action_response), 1)

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_trends_for_non_existing_action(self):
        with freeze_time("2020-01-04"):
            response = self.client.get(
                "/api/action/trends/", {"actions": jdumps([{"id": 4000000}])}
            ).json()
        self.assertEqual(len(response), 0)

        with freeze_time("2020-01-04"):
            response = self.client.get(
                "/api/action/trends/", {"events": jdumps([{"id": "DNE"}])}
            ).json()

        self.assertEqual(response[0]["data"], [0, 0, 0, 0, 0, 0, 0, 0])

    def test_dau_filtering(self):
        sign_up_action, person = self._create_events()
        with freeze_time("2020-01-02"):
            Person.objects.create(team=self.team, distinct_ids=["someone_else"])
            Event.objects.create(
                team=self.team, event="sign up", distinct_id="someone_else"
            )
        with freeze_time("2020-01-04"):
            action_response = self.client.get(
                "/api/action/trends/",
                data={"actions": jdumps([{"id": sign_up_action.id, "math": "dau"}]),},
            ).json()
            event_response = self.client.get(
                "/api/action/trends/",
                data={"events": jdumps([{"id": "sign up", "math": "dau"}]),},
            ).json()
        self.assertEqual(action_response[0]["data"][4], 1)
        self.assertEqual(action_response[0]["data"][5], 2)

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_dau_with_breakdown_filtering(self):
        sign_up_action, _ = self._create_events()
        with freeze_time("2020-01-02"):
            Event.objects.create(
                team=self.team,
                event="sign up",
                distinct_id="blabla",
                properties={"$some_property": "other_value"},
            )
        with freeze_time("2020-01-04"):
            action_response = self.client.get(
                "/api/action/trends/?breakdown=$some_property&actions=%s"
                % jdumps([{"id": sign_up_action.id, "math": "dau"}])
            ).json()
            event_response = self.client.get(
                "/api/action/trends/?breakdown=$some_property&events=%s"
                % jdumps([{"id": "sign up", "math": "dau"}])
            ).json()

        self.assertEqual(event_response[0]["label"], "sign up - other_value")
        self.assertEqual(event_response[1]["label"], "sign up - value")
        self.assertEqual(event_response[2]["label"], "sign up - Other")

        self.assertEqual(sum(event_response[0]["data"]), 1)
        self.assertEqual(event_response[0]["data"][5], 1)

        self.assertEqual(sum(event_response[2]["data"]), 1)
        self.assertEqual(event_response[2]["data"][4], 1)  # property not defined

        self.assertTrue(self._compare_entity_response(action_response, event_response))

    def test_people_endpoint(self):
        sign_up_action, person = self._create_events()
        person1 = Person.objects.create(team=self.team, distinct_ids=["person1"])
        Person.objects.create(team=self.team, distinct_ids=["person2"])
        Event.objects.create(
            team=self.team,
            event="sign up",
            distinct_id="person1",
            timestamp="2020-01-04T12:00:00Z",
        )
        Event.objects.create(
            team=self.team,
            event="sign up",
            distinct_id="person2",
            timestamp="2020-01-05T12:00:00Z",
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
            data={
                "date_from": "2020-01-04",
                "date_to": "2020-01-04",
                "type": "events",
                "entityId": "sign up",
            },
        ).json()

        self.assertEqual(action_response["results"][0]["people"][0]["id"], person1.pk)
        self.assertTrue(
            self._compare_entity_response(
                action_response["results"], event_response["results"], remove=[]
            )
        )

    def test_people_endpoint_paginated(self):

        for index in range(0, 150):
            Person.objects.create(team=self.team, distinct_ids=["person" + str(index)])
            Event.objects.create(
                team=self.team,
                event="sign up",
                distinct_id="person" + str(index),
                timestamp="2020-01-04T12:00:00Z",
            )

        event_response = self.client.get(
            "/api/action/people/",
            data={
                "date_from": "2020-01-04",
                "date_to": "2020-01-04",
                "type": "events",
                "entityId": "sign up",
            },
        ).json()
        self.assertEqual(len(event_response["results"][0]["people"]), 100)
        event_response_next = self.client.get(event_response["next"]).json()
        self.assertEqual(len(event_response_next["results"][0]["people"]), 50)

    def test_people_endpoint_with_intervals(self):
        sign_up_action, person = self._create_events()

        person1 = Person.objects.create(team=self.team, distinct_ids=["person1"])
        person2 = Person.objects.create(team=self.team, distinct_ids=["person2"])
        person3 = Person.objects.create(team=self.team, distinct_ids=["person3"])
        person4 = Person.objects.create(team=self.team, distinct_ids=["person4"])
        person5 = Person.objects.create(team=self.team, distinct_ids=["person5"])
        person6 = Person.objects.create(team=self.team, distinct_ids=["person6"])
        person7 = Person.objects.create(team=self.team, distinct_ids=["person7"])

        # solo
        Event.objects.create(
            team=self.team,
            event="sign up",
            distinct_id="person1",
            timestamp="2020-01-04T14:10:00Z",
        )
        # group by hour
        Event.objects.create(
            team=self.team,
            event="sign up",
            distinct_id="person2",
            timestamp="2020-01-04T16:30:00Z",
        )
        # group by hour
        Event.objects.create(
            team=self.team,
            event="sign up",
            distinct_id="person3",
            timestamp="2020-01-04T16:50:00Z",
        )
        # group by min
        Event.objects.create(
            team=self.team,
            event="sign up",
            distinct_id="person4",
            timestamp="2020-01-04T19:20:00Z",
        )
        # group by min
        Event.objects.create(
            team=self.team,
            event="sign up",
            distinct_id="person5",
            timestamp="2020-01-04T19:20:00Z",
        )
        # group by week and month
        Event.objects.create(
            team=self.team,
            event="sign up",
            distinct_id="person6",
            timestamp="2019-11-05T16:30:00Z",
        )
        # group by week and month
        Event.objects.create(
            team=self.team,
            event="sign up",
            distinct_id="person7",
            timestamp="2019-11-07T16:50:00Z",
        )

        # check solo hour
        action_response = self.client.get(
            "/api/action/people/",
            data={
                "interval": "hour",
                "date_from": "2020-01-04 14:00:00",
                "date_to": "2020-01-04 14:00:00",
                "type": "actions",
                "entityId": sign_up_action.id,
            },
        ).json()
        event_response = self.client.get(
            "/api/action/people/",
            data={
                "interval": "hour",
                "date_from": "2020-01-04 14:00:00",
                "date_to": "2020-01-04 14:00:00",
                "type": "events",
                "entityId": "sign up",
            },
        ).json()
        self.assertEqual(action_response["results"][0]["people"][0]["id"], person1.pk)
        self.assertEqual(len(action_response["results"][0]["people"]), 1)
        self.assertTrue(
            self._compare_entity_response(
                action_response["results"], event_response["results"], remove=[]
            )
        )

        # check grouped hour
        hour_grouped_action_response = self.client.get(
            "/api/action/people/",
            data={
                "interval": "hour",
                "date_from": "2020-01-04 16:00:00",
                "date_to": "2020-01-04 16:00:00",
                "type": "actions",
                "entityId": sign_up_action.id,
            },
        ).json()
        hour_grouped_grevent_response = self.client.get(
            "/api/action/people/",
            data={
                "interval": "hour",
                "date_from": "2020-01-04 16:00:00",
                "date_to": "2020-01-04 16:00:00",
                "type": "events",
                "entityId": "sign up",
            },
        ).json()
        self.assertEqual(
            hour_grouped_action_response["results"][0]["people"][0]["id"], person2.pk
        )
        self.assertEqual(
            hour_grouped_action_response["results"][0]["people"][1]["id"], person3.pk
        )
        self.assertEqual(len(hour_grouped_action_response["results"][0]["people"]), 2)
        self.assertTrue(
            self._compare_entity_response(
                hour_grouped_action_response["results"],
                hour_grouped_grevent_response["results"],
                remove=[],
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
        self.assertEqual(
            min_grouped_action_response["results"][0]["people"][0]["id"], person4.pk
        )
        self.assertEqual(
            min_grouped_action_response["results"][0]["people"][1]["id"], person5.pk
        )
        self.assertEqual(len(min_grouped_action_response["results"][0]["people"]), 2)
        self.assertTrue(
            self._compare_entity_response(
                min_grouped_action_response["results"],
                min_grouped_grevent_response["results"],
                remove=[],
            )
        )

        # check grouped week
        week_grouped_action_response = self.client.get(
            "/api/action/people/",
            data={
                "interval": "week",
                "date_from": "2019-11-01",
                "date_to": "2019-11-01",
                "type": "actions",
                "entityId": sign_up_action.id,
            },
        ).json()
        week_grouped_grevent_response = self.client.get(
            "/api/action/people/",
            data={
                "interval": "week",
                "date_from": "2019-11-01",
                "date_to": "2019-11-01",
                "type": "events",
                "entityId": "sign up",
            },
        ).json()
        self.assertEqual(
            week_grouped_action_response["results"][0]["people"][0]["id"], person6.pk
        )
        self.assertEqual(
            week_grouped_action_response["results"][0]["people"][1]["id"], person7.pk
        )
        self.assertEqual(len(week_grouped_action_response["results"][0]["people"]), 2)
        self.assertTrue(
            self._compare_entity_response(
                week_grouped_action_response["results"],
                week_grouped_grevent_response["results"],
                remove=[],
            )
        )

        # check grouped month
        month_group_action_response = self.client.get(
            "/api/action/people/",
            data={
                "interval": "month",
                "date_from": "2019-11-01",
                "date_to": "2019-11-01",
                "type": "actions",
                "entityId": sign_up_action.id,
            },
        ).json()
        month_group_grevent_response = self.client.get(
            "/api/action/people/",
            data={
                "interval": "month",
                "date_from": "2019-11-01",
                "date_to": "2019-11-01",
                "type": "events",
                "entityId": "sign up",
            },
        ).json()
        self.assertEqual(
            month_group_action_response["results"][0]["people"][0]["id"], person6.pk
        )
        self.assertEqual(
            month_group_action_response["results"][0]["people"][1]["id"], person7.pk
        )
        self.assertEqual(len(month_group_action_response["results"][0]["people"]), 2)
        self.assertTrue(
            self._compare_entity_response(
                month_group_action_response["results"],
                month_group_grevent_response["results"],
                remove=[],
            )
        )

    def _create_multiple_people(self):
        person1 = Person.objects.create(
            team=self.team, distinct_ids=["person1"], properties={"name": "person1"}
        )
        Event.objects.create(
            team=self.team,
            event="watched movie",
            distinct_id="person1",
            timestamp="2020-01-01T12:00:00Z",
        )

        person2 = Person.objects.create(
            team=self.team, distinct_ids=["person2"], properties={"name": "person2"}
        )
        Event.objects.create(
            team=self.team,
            event="watched movie",
            distinct_id="person2",
            timestamp="2020-01-01T12:00:00Z",
        )
        Event.objects.create(
            team=self.team,
            event="watched movie",
            distinct_id="person2",
            timestamp="2020-01-02T12:00:00Z",
        )
        # same day
        Event.objects.create(
            team=self.team,
            event="watched movie",
            distinct_id="person2",
            timestamp="2020-01-02T12:00:00Z",
        )

        person3 = Person.objects.create(
            team=self.team, distinct_ids=["person3"], properties={"name": "person3"}
        )
        Event.objects.create(
            team=self.team,
            event="watched movie",
            distinct_id="person3",
            timestamp="2020-01-01T12:00:00Z",
        )
        Event.objects.create(
            team=self.team,
            event="watched movie",
            distinct_id="person3",
            timestamp="2020-01-02T12:00:00Z",
        )
        Event.objects.create(
            team=self.team,
            event="watched movie",
            distinct_id="person3",
            timestamp="2020-01-03T12:00:00Z",
        )

        person4 = Person.objects.create(
            team=self.team, distinct_ids=["person4"], properties={"name": "person4"}
        )
        Event.objects.create(
            team=self.team,
            event="watched movie",
            distinct_id="person4",
            timestamp="2020-01-05T12:00:00Z",
        )
        return (person1, person2, person3, person4)

    def test_stickiness(self):
        person1 = self._create_multiple_people()[0]

        watched_movie = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=watched_movie, event="watched movie")
        watched_movie.calculate_events()

        with freeze_time("2020-01-08T13:01:01Z"):
            action_response = self.client.get(
                "/api/action/trends/",
                data={
                    "shown_as": "Stickiness",
                    "actions": jdumps([{"id": watched_movie.id}]),
                },
            ).json()
            event_response = self.client.get(
                "/api/action/trends/",
                data={
                    "shown_as": "Stickiness",
                    "date_from": "2020-01-01",
                    "date_to": "2020-01-08",
                    "events": jdumps([{"id": "watched movie"}]),
                },
            ).json()
        self.assertEqual(action_response[0]["count"], 4)
        self.assertEqual(action_response[0]["labels"][0], "1 day")
        self.assertEqual(action_response[0]["data"][0], 2)
        self.assertEqual(action_response[0]["labels"][1], "2 days")
        self.assertEqual(action_response[0]["data"][1], 1)
        self.assertEqual(action_response[0]["labels"][2], "3 days")
        self.assertEqual(action_response[0]["data"][2], 1)
        self.assertEqual(action_response[0]["labels"][6], "7 days")
        self.assertEqual(action_response[0]["data"][6], 0)

        self.assertTrue(self._compare_entity_response(action_response, event_response))

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
        self.assertEqual(action_response["results"][0]["people"][0]["id"], person1.pk)

        self.assertTrue(
            self._compare_entity_response(
                action_response["results"], event_response["results"], remove=[]
            )
        )

        # test all time
        response = self.client.get(
            "/api/action/trends/",
            data={
                "shown_as": "Stickiness",
                "date_from": "all",
                "date_to": "2020-01-07",
                "events": jdumps([{"id": "watched_movie"}]),
            },
        ).json()

        self.assertEqual(len(response[0]["data"]), 7)

    def test_breakdown_by_cohort(self):
        person1, person2, person3, person4 = self._create_multiple_people()
        cohort = Cohort.objects.create(
            name="cohort1", team=self.team, groups=[{"properties": {"name": "person1"}}]
        )
        cohort2 = Cohort.objects.create(
            name="cohort2", team=self.team, groups=[{"properties": {"name": "person2"}}]
        )
        cohort3 = Cohort.objects.create(
            name="cohort3",
            team=self.team,
            groups=[
                {"properties": {"name": "person1"}},
                {"properties": {"name": "person2"}},
            ],
        )
        cohort.calculate_people()
        cohort2.calculate_people()
        cohort3.calculate_people()
        action = Action.objects.create(name="watched movie", team=self.team)
        ActionStep.objects.create(action=action, event="watched movie")
        action.calculate_events()

        with freeze_time("2020-01-04T13:01:01Z"):
            event_response = self.client.get(
                "/api/action/trends/?date_from=-14d&breakdown=%s&breakdown_type=cohort&events=%s"
                % (
                    jdumps([cohort.pk, cohort2.pk, cohort3.pk, "all"]),
                    jdumps(
                        [
                            {
                                "id": "watched movie",
                                "name": "watched movie",
                                "type": "events",
                                "order": 0,
                            }
                        ]
                    ),
                )
            ).json()
            action_response = self.client.get(
                "/api/action/trends/?date_from=-14d&breakdown=%s&breakdown_type=cohort&actions=%s"
                % (
                    jdumps([cohort.pk, cohort2.pk, cohort3.pk, "all"]),
                    jdumps([{"id": action.pk, "type": "actions", "order": 0}]),
                )
            ).json()

        self.assertEqual(event_response[0]["label"], "watched movie - cohort1")
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

        people = self.client.get(
            "/api/action/people/",
            data={
                "date_from": "2020-01-01",
                "date_to": "2020-01-07",
                "type": "events",
                "entityId": "watched movie",
                "breakdown_type": "cohort",
                "breakdown_value": cohort.pk,
                "breakdown": [cohort.pk],  # this shouldn't do anything
            },
        ).json()
        self.assertEqual(len(people["results"][0]["people"]), 1)
        self.assertEqual(people["results"][0]["people"][0]["id"], person1.pk)

        # all people
        people = self.client.get(
            "/api/action/people/",
            data={
                "date_from": "2020-01-01",
                "date_to": "2020-01-07",
                "type": "events",
                "entityId": "watched movie",
                "breakdown_type": "cohort",
                "breakdown_value": "all",
                "breakdown": [cohort.pk],
            },
        ).json()
        self.assertEqual(len(people["results"][0]["people"]), 4)
        self.assertEqual(people["results"][0]["people"][0]["id"], person1.pk)

    def test_breakdown_by_person_property(self):
        person1, person2, person3, person4 = self._create_multiple_people()
        action = Action.objects.create(name="watched movie", team=self.team)
        ActionStep.objects.create(action=action, event="watched movie")
        action.calculate_events()

        with freeze_time("2020-01-04T13:01:01Z"):
            event_response = self.client.get(
                "/api/action/trends/?date_from=-14d&breakdown=%s&breakdown_type=person&events=%s"
                % (
                    "name",
                    jdumps(
                        [
                            {
                                "id": "watched movie",
                                "name": "watched movie",
                                "type": "events",
                                "order": 0,
                            }
                        ]
                    ),
                )
            ).json()
            action_response = self.client.get(
                "/api/action/trends/?date_from=-14d&breakdown=%s&breakdown_type=person&actions=%s"
                % ("name", jdumps([{"id": action.pk, "type": "actions", "order": 0}]),)
            ).json()

        self.assertEqual(event_response[0]["count"], 3)
        self.assertEqual(event_response[0]["breakdown_value"], "person2")

        self.assertEqual(event_response[1]["count"], 1)
        self.assertEqual(event_response[1]["breakdown_value"], "person1")

        self.assertEqual(event_response[2]["count"], 3)
        self.assertEqual(event_response[2]["breakdown_value"], "person3")

        self.assertEqual(event_response[3]["count"], 0)
        self.assertEqual(event_response[3]["breakdown_value"], "person4")

        self.assertTrue(self._compare_entity_response(event_response, action_response,))

        people = self.client.get(
            "/api/action/people/",
            data={
                "date_from": "2020-01-01",
                "date_to": "2020-01-07",
                "type": "events",
                "entityId": "watched movie",
                "breakdown_type": "person",
                "breakdown_value": "person3",
                "breakdown": "name",
            },
        ).json()
        self.assertEqual(len(people["results"][0]["people"]), 1)
        self.assertEqual(people["results"][0]["people"][0]["name"], "person3")


class TestRetention(TransactionBaseTest):
    def test_retention(self):
        person1 = Person.objects.create(
            team=self.team, distinct_ids=["person1", "alias1"]
        )
        person2 = Person.objects.create(team=self.team, distinct_ids=["person2"])

        self._create_pageviews(
            [
                ("person1", self._date(0)),
                ("person1", self._date(1)),
                ("person1", self._date(2)),
                ("person1", self._date(5)),
                ("alias1", self._date(5, 9)),
                ("person1", self._date(6)),
                ("person2", self._date(1)),
                ("person2", self._date(2)),
                ("person2", self._date(3)),
                ("person2", self._date(6)),
            ]
        )

        result = calculate_retention(
            Filter(data={"date_from": self._date(0, hour=0)}), self.team, total_days=7
        )

        self.assertEqual(len(result["data"]), 7)
        self.assertEqual(
            self.pluck(result["data"], "label"),
            ["Day 0", "Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6"],
        )
        self.assertEqual(result["data"][0]["date"], "Wed. 10 June")

        self.assertEqual(
            self.pluck(result["data"], "values"),
            [
                [1, 1, 1, 0, 0, 1, 1],
                [2, 2, 1, 0, 1, 2],
                [2, 1, 0, 1, 2],
                [1, 0, 0, 1],
                [0, 0, 0],
                [1, 1],
                [2],
            ],
        )

    def _create_pageviews(self, user_and_timestamps):
        for distinct_id, timestamp in user_and_timestamps:
            Event.objects.create(
                team=self.team,
                event="$pageview",
                distinct_id=distinct_id,
                timestamp=timestamp,
            )

    def _date(self, day, hour=5):
        return datetime(2020, 6, 10 + day, hour).isoformat()

    def pluck(self, list_of_dicts, key):
        return [d[key] for d in list_of_dicts]
