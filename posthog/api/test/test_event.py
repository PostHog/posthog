import json
import uuid
from typing import Union
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status

from posthog.constants import AnalyticsDBMS
from posthog.models import (
    Action,
    ActionStep,
    Element,
    Event,
    Organization,
    Person,
    Team,
    User,
)
from posthog.queries.sessions.sessions_list import SESSIONS_LIST_DEFAULT_LIMIT
from posthog.test.base import APIBaseTest
from posthog.utils import relative_date_parse


def factory_test_event_api(event_factory, person_factory, _):
    class TestEvents(APIBaseTest):
        ENDPOINT = "event"

        def test_filter_events(self):
            person_factory(
                properties={"email": "tim@posthog.com"},
                team=self.team,
                distinct_ids=["2", "some-random-uid"],
                is_identified=True,
            )

            event_factory(
                event="$autocapture",
                team=self.team,
                distinct_id="2",
                properties={"$ip": "8.8.8.8"},
                elements=[Element(tag_name="button", text="something"), Element(tag_name="div")],
            )
            event_factory(
                event="$pageview", team=self.team, distinct_id="some-random-uid", properties={"$ip": "8.8.8.8"}
            )
            event_factory(
                event="$pageview", team=self.team, distinct_id="some-other-one", properties={"$ip": "8.8.8.8"}
            )

            expected_queries = 3 if settings.PRIMARY_DB == AnalyticsDBMS.CLICKHOUSE else 10

            with self.assertNumQueries(expected_queries):
                response = self.client.get("/api/event/?distinct_id=2").json()
            self.assertEqual(
                response["results"][0]["person"],
                {"distinct_ids": ["2"], "is_identified": True, "properties": {"email": "tim@posthog.com"}},
            )
            self.assertEqual(response["results"][0]["elements"][0]["tag_name"], "button")
            self.assertEqual(response["results"][0]["elements"][0]["order"], 0)
            self.assertEqual(response["results"][0]["elements"][1]["order"], 1)

        def test_filter_events_by_event_name(self):
            person_factory(
                properties={"email": "tim@posthog.com"}, team=self.team, distinct_ids=["2", "some-random-uid"],
            )
            event_factory(
                event="event_name", team=self.team, distinct_id="2", properties={"$ip": "8.8.8.8"},
            )
            event_factory(
                event="another event", team=self.team, distinct_id="2", properties={"$ip": "8.8.8.8"},
            )

            expected_queries = 3 if settings.PRIMARY_DB == AnalyticsDBMS.CLICKHOUSE else 7

            with self.assertNumQueries(expected_queries):
                response = self.client.get("/api/event/?event=event_name").json()
            self.assertEqual(response["results"][0]["event"], "event_name")

        def test_filter_events_by_properties(self):
            person_factory(
                properties={"email": "tim@posthog.com"}, team=self.team, distinct_ids=["2", "some-random-uid"],
            )
            event_factory(
                event="event_name", team=self.team, distinct_id="2", properties={"$browser": "Chrome"},
            )
            event2 = event_factory(
                event="event_name", team=self.team, distinct_id="2", properties={"$browser": "Safari"},
            )

            expected_queries = 3 if settings.PRIMARY_DB == AnalyticsDBMS.CLICKHOUSE else 7

            with self.assertNumQueries(expected_queries):
                response = self.client.get(
                    "/api/event/?properties=%s" % (json.dumps([{"key": "$browser", "value": "Safari"}]))
                ).json()
            self.assertEqual(response["results"][0]["id"], event2.pk)

            properties = "invalid_json"

            response = self.client.get(f"/api/event/?properties={properties}")

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertDictEqual(
                response.json(), self.validation_error_response("Properties are unparsable!", "invalid_input")
            )

        def test_filter_by_person(self):
            person = person_factory(
                properties={"email": "tim@posthog.com"}, distinct_ids=["2", "some-random-uid"], team=self.team,
            )

            event_factory(event="random event", team=self.team, distinct_id="2", properties={"$ip": "8.8.8.8"})
            event_factory(
                event="random event", team=self.team, distinct_id="some-random-uid", properties={"$ip": "8.8.8.8"}
            )
            event_factory(
                event="random event", team=self.team, distinct_id="some-other-one", properties={"$ip": "8.8.8.8"}
            )

            response = self.client.get(f"/api/event/?person_id={person.pk}").json()
            self.assertEqual(len(response["results"]), 2)
            self.assertEqual(response["results"][0]["elements"], [])

        def test_filter_by_nonexisting_person(self):
            response = self.client.get(f"/api/event/?person_id=5555555555")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["results"]), 0)

        def _signup_event(self, distinct_id: str):
            sign_up = event_factory(
                event="$autocapture",
                distinct_id=distinct_id,
                team=self.team,
                elements=[Element(tag_name="button", text="Sign up!")],
            )
            return sign_up

        def _pay_event(self, distinct_id: str):
            sign_up = event_factory(
                event="$autocapture",
                distinct_id=distinct_id,
                team=self.team,
                elements=[
                    Element(tag_name="button", text="Pay $10"),
                    # check we're not duplicating
                    Element(tag_name="div", text="Sign up!"),
                ],
            )
            return sign_up

        def _movie_event(self, distinct_id: str):
            sign_up = event_factory(
                event="$autocapture",
                distinct_id=distinct_id,
                team=self.team,
                elements=[
                    Element(
                        tag_name="a",
                        attr_class=["watch_movie", "play"],
                        text="Watch now",
                        attr_id="something",
                        href="/movie",
                    ),
                    Element(tag_name="div", href="/movie"),
                ],
            )
            return sign_up

        def test_custom_event_values(self):
            events = ["test", "new event", "another event"]
            for event in events:
                event_factory(
                    distinct_id="bla",
                    event=event,
                    team=self.team,
                    properties={"random_prop": "don't include", "some other prop": "with some text"},
                )
            response = self.client.get("/api/event/values/?key=custom_event").json()
            self.assertListEqual(sorted(events), sorted([event["name"] for event in response]))

        def test_event_property_values(self):

            with freeze_time("2020-01-10"):
                event_factory(
                    distinct_id="bla",
                    event="random event",
                    team=self.team,
                    properties={"random_prop": "don't include", "some other prop": "with some text"},
                )

            with freeze_time("2020-01-20 20:00:00"):
                event_factory(
                    distinct_id="bla",
                    event="random event",
                    team=self.team,
                    properties={"random_prop": "asdf", "some other prop": "with some text"},
                )
                event_factory(
                    distinct_id="bla", event="random event", team=self.team, properties={"random_prop": "asdf"}
                )
                event_factory(
                    distinct_id="bla", event="random event", team=self.team, properties={"random_prop": "qwerty"}
                )
                event_factory(distinct_id="bla", event="random event", team=self.team, properties={"random_prop": True})
                event_factory(
                    distinct_id="bla", event="random event", team=self.team, properties={"random_prop": False}
                )
                event_factory(
                    distinct_id="bla",
                    event="random event",
                    team=self.team,
                    properties={"random_prop": {"first_name": "Mary", "last_name": "Smith"}},
                )
                event_factory(
                    distinct_id="bla", event="random event", team=self.team, properties={"something_else": "qwerty"}
                )
                event_factory(distinct_id="bla", event="random event", team=self.team, properties={"random_prop": 565})
                event_factory(
                    distinct_id="bla",
                    event="random event",
                    team=self.team,
                    properties={"random_prop": ["item1", "item2"]},
                )
                event_factory(
                    distinct_id="bla", event="random event", team=self.team, properties={"random_prop": ["item3"]}
                )

                team2 = Organization.objects.bootstrap(None)[2]
                event_factory(distinct_id="bla", event="random event", team=team2, properties={"random_prop": "abcd"})
                response = self.client.get("/api/event/values/?key=random_prop").json()

                keys = [resp["name"].replace(" ", "") for resp in response]
                self.assertCountEqual(
                    keys,
                    [
                        "asdf",
                        "qwerty",
                        "565",
                        "false",
                        "true",
                        '{"first_name":"Mary","last_name":"Smith"}',
                        "item1",
                        "item2",
                        "item3",
                    ],
                )
                self.assertEqual(len(response), 9)

                response = self.client.get("/api/event/values/?key=random_prop&value=qw").json()
                self.assertEqual(response[0]["name"], "qwerty")

                response = self.client.get("/api/event/values/?key=random_prop&value=6").json()
                self.assertEqual(response[0]["name"], "565")

        def test_before_and_after(self):
            user = self._create_user("tim")
            self.client.force_login(user)
            person_factory(
                properties={"email": "tim@posthog.com"}, team=self.team, distinct_ids=["2", "some-random-uid"],
            )

            with freeze_time("2020-01-10"):
                event1 = event_factory(team=self.team, event="sign up", distinct_id="2")
            with freeze_time("2020-01-8"):
                event2 = event_factory(team=self.team, event="sign up", distinct_id="2")
            with freeze_time("2020-01-7"):
                event3 = event_factory(team=self.team, event="random other event", distinct_id="2")

            action = Action.objects.create(team=self.team)
            ActionStep.objects.create(action=action, event="sign up")
            action.calculate_events()

            response = self.client.get("/api/event/?after=2020-01-09T00:00:00.000Z&action_id=%s" % action.pk).json()
            self.assertEqual(len(response["results"]), 1)
            self.assertEqual(response["results"][0]["id"], event1.pk)

            response = self.client.get("/api/event/?before=2020-01-09T00:00:00.000Z&action_id=%s" % action.pk).json()
            self.assertEqual(len(response["results"]), 1)
            self.assertEqual(response["results"][0]["id"], event2.pk)

            # without action
            response = self.client.get("/api/event/?after=2020-01-09T00:00:00.000Z").json()
            self.assertEqual(len(response["results"]), 1)
            self.assertEqual(response["results"][0]["id"], event1.pk)

            response = self.client.get("/api/event/?before=2020-01-09T00:00:00.000Z").json()
            self.assertEqual(len(response["results"]), 2)
            self.assertEqual(response["results"][0]["id"], event2.pk)
            self.assertEqual(response["results"][1]["id"], event3.pk)

        def test_pagination(self):
            person_factory(team=self.team, distinct_ids=["1"])
            for idx in range(0, 150):
                event_factory(
                    team=self.team,
                    event="some event",
                    distinct_id="1",
                    timestamp=timezone.now() - relativedelta(months=11) + relativedelta(days=idx, seconds=idx),
                )
            response = self.client.get("/api/event/?distinct_id=1").json()
            self.assertEqual(len(response["results"]), 100)
            self.assertIn("http://testserver/api/event/?distinct_id=1&before=", response["next"])

            page2 = self.client.get(response["next"]).json()
            from posthog.ee import is_clickhouse_enabled

            if is_clickhouse_enabled():
                from ee.clickhouse.client import sync_execute

                self.assertEqual(
                    sync_execute("select count(*) from events where team_id = %(team_id)s", {"team_id": self.team.pk})[
                        0
                    ][0],
                    150,
                )

            self.assertEqual(len(page2["results"]), 50)

        def test_action_no_steps(self):
            action = Action.objects.create(team=self.team)
            action.calculate_events()

            response = self.client.get("/api/event/?action_id=%s" % action.pk)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["results"]), 0)

        def test_get_single_action(self):
            event1 = event_factory(team=self.team, event="sign up", distinct_id="2", properties={"key": "test_val"})
            response = self.client.get("/api/event/%s/" % event1.id)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["event"], "sign up")
            self.assertEqual(response.json()["properties"], {"key": "test_val"})

        def test_events_sessions_basic(self):
            with freeze_time("2012-01-14T03:21:34.000Z"):
                event_factory(team=self.team, event="1st action", distinct_id="1")
                event_factory(team=self.team, event="1st action", distinct_id="2")
            with freeze_time("2012-01-14T03:25:34.000Z"):
                event_factory(team=self.team, event="2nd action", distinct_id="1")
                event_factory(team=self.team, event="2nd action", distinct_id="2")
            with freeze_time("2012-01-15T03:59:34.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="2")
            with freeze_time("2012-01-15T03:59:35.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="1")
            with freeze_time("2012-01-15T04:01:34.000Z"):
                event_factory(team=self.team, event="4th action", distinct_id="1", properties={"$os": "Mac OS X"})
                event_factory(team=self.team, event="4th action", distinct_id="2", properties={"$os": "Windows 95"})

            with freeze_time("2012-01-15T04:01:34.000Z"):
                response = self.client.get("/api/event/sessions/",).json()

            self.assertEqual(len(response["result"]), 2)

            response = self.client.get("/api/event/sessions/?date_from=2012-01-14&date_to=2012-01-15",).json()
            self.assertEqual(len(response["result"]), 4)

            # 4 sessions were already created above
            for i in range(SESSIONS_LIST_DEFAULT_LIMIT - 4):
                with freeze_time(relative_date_parse("2012-01-15T04:01:34.000Z") + relativedelta(hours=i)):
                    event_factory(team=self.team, event="action {}".format(i), distinct_id=str(i + 3))

            response = self.client.get("/api/event/sessions/?date_from=2012-01-14&date_to=2012-01-17",).json()
            self.assertEqual(len(response["result"]), SESSIONS_LIST_DEFAULT_LIMIT)
            self.assertIsNone(response.get("pagination"))

            for i in range(2):
                with freeze_time(relative_date_parse("2012-01-15T04:01:34.000Z") + relativedelta(hours=i + 46)):
                    event_factory(team=self.team, event="action {}".format(i), distinct_id=str(i + 49))

            response = self.client.get("/api/event/sessions/?date_from=2012-01-14&date_to=2012-01-17",).json()
            self.assertEqual(len(response["result"]), SESSIONS_LIST_DEFAULT_LIMIT)
            self.assertIsNotNone(response["pagination"])

        def test_events_nonexistent_cohort_handling(self):
            response_nonexistent_property = self.client.get(
                f"/api/event/sessions/?filters={json.dumps([{'type':'property','key':'abc','value':'xyz'}])}"
            ).json()
            response_nonexistent_cohort = self.client.get(
                f"/api/event/sessions/?filters={json.dumps([{'type':'cohort','key':'id','value':2137}])}"
            ).json()

            self.assertEqual(response_nonexistent_property, response_nonexistent_cohort)  # Both caes just empty

        def test_event_sessions_by_id(self):
            another_team = Team.objects.create(organization=self.organization)

            Person.objects.create(team=self.team, distinct_ids=["1"])
            Person.objects.create(team=another_team, distinct_ids=["1"])
            with freeze_time("2012-01-14T03:21:34.000Z"):
                event_factory(team=self.team, event="1st action", distinct_id="1")
                event_factory(team=self.team, event="1st action", distinct_id="2")
            with freeze_time("2012-01-14T03:25:34.000Z"):
                event_factory(team=self.team, event="2nd action", distinct_id="1")
                event_factory(team=another_team, event="2nd action", distinct_id="1")
                event_factory(team=self.team, event="2nd action", distinct_id="2")
            with freeze_time("2012-01-15T03:59:35.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="1")
            with freeze_time("2012-01-15T04:01:34.000Z"):
                event_factory(team=self.team, event="4th action", distinct_id="1", properties={"$os": "Mac OS X"})
                event_factory(team=self.team, event="4th action", distinct_id="2", properties={"$os": "Windows 95"})

            with freeze_time("2012-01-15T04:01:34.000Z"):
                response_person_1 = self.client.get("/api/event/sessions/?distinct_id=1",).json()

            self.assertEqual(len(response_person_1["result"]), 1)

        def test_events_in_future(self):
            with freeze_time("2012-01-15T04:01:34.000Z"):
                event_factory(team=self.team, event="5th action", distinct_id="2", properties={"$os": "Windows 95"})
            # Don't show events more than 5 seconds in the future
            with freeze_time("2012-01-15T04:01:44.000Z"):
                event_factory(team=self.team, event="5th action", distinct_id="2", properties={"$os": "Windows 95"})
            with freeze_time("2012-01-15T04:01:34.000Z"):
                response = self.client.get("/api/event/").json()
            self.assertEqual(len(response["results"]), 1)

        def test_session_events(self):
            another_team = Team.objects.create(organization=self.organization)

            Person.objects.create(team=self.team, distinct_ids=["1"])
            Person.objects.create(team=another_team, distinct_ids=["1"])

            with freeze_time("2012-01-14T03:21:34.000Z"):
                event_factory(team=self.team, event="1st action", distinct_id="1")

            with freeze_time("2012-01-14T03:25:34.000Z"):
                event_factory(team=self.team, event="2nd action", distinct_id="1")
                event_factory(team=another_team, event="2nd action", distinct_id="1")
                event_factory(team=self.team, event="2nd action", distinct_id="2")

            with freeze_time("2012-01-15T03:59:35.000Z"):
                event_factory(team=self.team, event="3rd action", distinct_id="1")

            with freeze_time("2012-01-15T04:01:34.000Z"):
                event_factory(team=self.team, event="4th action", distinct_id="1", properties={"$os": "Mac OS X"})

            response = self.client.get(
                f"/api/event/session_events?distinct_id=1&date_from=2012-01-14T03:25:34&date_to=2012-01-15T04:00:00"
            ).json()
            self.assertEqual(len(response["result"]), 2)
            self.assertEqual(response["result"][0]["event"], "2nd action")
            self.assertEqual(response["result"][1]["event"], "3rd action")

        @patch("posthog.api.event.EventViewSet.CSV_EXPORT_LIMIT", 10)
        def test_events_csv_export_with_limit(self):
            with freeze_time("2012-01-15T04:01:34.000Z"):
                for _ in range(12):
                    event_factory(team=self.team, event="5th action", distinct_id="2", properties={"$os": "Windows 95"})
                response = self.client.get("/api/event.csv")
            self.assertEqual(
                len(response.content.splitlines()),
                11,
                "CSV export should return up to CSV_EXPORT_LIMIT events (+ headers row)",
            )

        def test_get_event_by_id(self):
            event_id: Union[str, int] = 12345

            if settings.PRIMARY_DB == AnalyticsDBMS.CLICKHOUSE:
                from ee.clickhouse.models.event import create_event

                event_id = "01793986-dc4b-0000-93e8-1fb646df3a93"
                Event(
                    pk=create_event(
                        team=self.team,
                        event="event",
                        distinct_id="1",
                        timestamp=timezone.now(),
                        event_uuid=uuid.UUID(event_id),
                    )
                )
            else:
                event_factory(team=self.team, event="event", distinct_id="1", timestamp=timezone.now(), id=event_id)

            response = self.client.get(f"/api/event/{event_id}",)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["event"], "event")

            response = self.client.get(f"/api/event/123456",)
            # EE will inform the user the ID passed is not a valid UUID
            self.assertIn(response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_400_BAD_REQUEST])

            response = self.client.get(f"/api/event/im_a_string_not_an_integer",)
            self.assertIn(response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_400_BAD_REQUEST])

        def test_limit(self):
            person_factory(
                properties={"email": "tim@posthog.com"},
                team=self.team,
                distinct_ids=["2", "some-random-uid"],
                is_identified=True,
            )

            event_factory(
                event="$autocapture",
                team=self.team,
                distinct_id="2",
                properties={"$ip": "8.8.8.8"},
                elements=[Element(tag_name="button", text="something"), Element(tag_name="div")],
            )
            event_factory(
                event="$pageview", team=self.team, distinct_id="some-random-uid", properties={"$ip": "8.8.8.8"}
            )
            event_factory(
                event="$pageview", team=self.team, distinct_id="some-other-one", properties={"$ip": "8.8.8.8"}
            )

            response = self.client.get("/api/event/?limit=1").json()
            self.assertEqual(1, len(response["results"]))

            response = self.client.get("/api/event/?limit=2").json()
            self.assertEqual(2, len(response["results"]))

        def test_get_events_with_specified_token(self):
            _, _, user = User.objects.bootstrap("Test", "team2@posthog.com", None)

            assert user.team is not None
            assert self.team is not None

            self.assertNotEqual(user.team.id, self.team.id)

            event1 = event_factory(team=self.team, event="sign up", distinct_id="2", properties={"key": "test_val"})
            event2 = event_factory(team=user.team, event="sign up", distinct_id="2", properties={"key": "test_val"})

            response_team1 = self.client.get(f"/api/event/{event1.id}/")
            response_team1_token = self.client.get(f"/api/event/{event1.id}/", data={"token": self.team.api_token})

            response_team2_event1 = self.client.get(f"/api/event/{event1.id}/", data={"token": user.team.api_token})
            response_team2_event2 = self.client.get(f"/api/event/{event2.id}/", data={"token": user.team.api_token})

            self.assertEqual(response_team1.json(), response_team1_token.json())
            self.assertNotEqual(response_team1.json(), response_team2_event2.json())
            self.assertEqual(response_team2_event1.status_code, status.HTTP_404_NOT_FOUND)
            self.assertEqual(response_team2_event2.status_code, status.HTTP_200_OK)

            response_invalid_token = self.client.get(f"/api/event?token=invalid")
            self.assertEqual(response_invalid_token.status_code, 401)

    return TestEvents


def _create_action(**kwargs):
    team = kwargs.pop("team")
    name = kwargs.pop("name")
    action = Action.objects.create(team=team, name=name)
    ActionStep.objects.create(action=action, event=name)
    action.calculate_events()
    return action


class TestEvent(factory_test_event_api(Event.objects.create, Person.objects.create, _create_action)):  # type: ignore
    pass
