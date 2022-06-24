import json
from datetime import datetime
from unittest.mock import patch
from urllib.parse import unquote, urlencode

import pytz
from dateutil import parser
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from freezegun import freeze_time
from rest_framework import status

from posthog.models import Action, ActionStep, Element, Organization, Person, User
from posthog.models.cohort import Cohort
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
    test_with_materialized_columns,
)
from posthog.test.test_journeys import journeys_for


class TestEvents(ClickhouseTestMixin, APIBaseTest):
    ENDPOINT = "event"

    def test_filter_events(self):
        _create_person(
            properties={"email": "tim@posthog.com"},
            team=self.team,
            distinct_ids=["2", "some-random-uid"],
            is_identified=True,
        )

        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="2",
            properties={"$ip": "8.8.8.8"},
            elements=[Element(tag_name="button", text="something"), Element(tag_name="div")],
        )
        _create_event(event="$pageview", team=self.team, distinct_id="some-random-uid", properties={"$ip": "8.8.8.8"})
        _create_event(event="$pageview", team=self.team, distinct_id="some-other-one", properties={"$ip": "8.8.8.8"})
        flush_persons_and_events()

        expected_queries = (
            8  # Django session, PostHog user, PostHog team, PostHog org membership, 2x team(?), person and distinct id
        )

        with self.assertNumQueries(expected_queries):
            response = self.client.get(f"/api/projects/{self.team.id}/events/?distinct_id=2").json()
        self.assertEqual(
            response["results"][0]["person"],
            {"distinct_ids": ["2"], "is_identified": True, "properties": {"email": "tim@posthog.com"}},
        )
        self.assertEqual(response["results"][0]["elements"][0]["tag_name"], "button")
        self.assertEqual(response["results"][0]["elements"][0]["order"], 0)
        self.assertEqual(response["results"][0]["elements"][1]["order"], 1)

    def test_filter_events_by_event_name(self):
        _create_person(
            properties={"email": "tim@posthog.com"}, team=self.team, distinct_ids=["2", "some-random-uid"],
        )
        _create_event(
            event="event_name", team=self.team, distinct_id="2", properties={"$ip": "8.8.8.8"},
        )
        _create_event(
            event="another event", team=self.team, distinct_id="2", properties={"$ip": "8.8.8.8"},
        )
        flush_persons_and_events()

        expected_queries = (
            8  # Django session, PostHog user, PostHog team, PostHog org membership, 2x team(?), person and distinct id
        )

        with self.assertNumQueries(expected_queries):
            response = self.client.get(f"/api/projects/{self.team.id}/events/?event=event_name").json()
        self.assertEqual(response["results"][0]["event"], "event_name")

    def test_filter_events_by_properties(self):
        _create_person(
            properties={"email": "tim@posthog.com"}, team=self.team, distinct_ids=["2", "some-random-uid"],
        )
        _create_event(
            event="event_name", team=self.team, distinct_id="2", properties={"$browser": "Chrome"},
        )
        event2_uuid = _create_event(
            event="event_name", team=self.team, distinct_id="2", properties={"$browser": "Safari"},
        )
        flush_persons_and_events()

        expected_queries = (
            10  # Django session, PostHog user, PostHog team, PostHog org membership, 2x team(?), person and distinct id
        )

        with self.assertNumQueries(expected_queries):
            response = self.client.get(
                f"/api/projects/{self.team.id}/events/?properties=%s"
                % (json.dumps([{"key": "$browser", "value": "Safari"}]))
            ).json()
        self.assertEqual(response["results"][0]["id"], event2_uuid)

        properties = "invalid_json"

        response = self.client.get(f"/api/projects/{self.team.id}/events/?properties={properties}")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertDictEqual(
            response.json(), self.validation_error_response("Properties are unparsable!", "invalid_input")
        )

    def test_filter_events_by_precalculated_cohort(self):
        p1 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p1"], properties={"key": "value"})
        _create_event(
            team=self.team, event="$pageview", distinct_id="p1", timestamp="2020-01-02T12:00:00Z",
        )

        p2 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p2"], properties={"key": "value"})
        _create_event(
            team=self.team, event="$pageview", distinct_id="p2", timestamp="2020-01-02T12:00:00Z",
        )

        p3 = Person.objects.create(team_id=self.team.pk, distinct_ids=["p3"], properties={"key_2": "value_2"})
        _create_event(
            team=self.team, event="$pageview", distinct_id="p3", timestamp="2020-01-02T12:00:00Z",
        )

        cohort1 = Cohort.objects.create(
            team=self.team,
            name="cohort_1",
            groups=[{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
        )

        cohort1.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):  # Normally this is False in tests
            with freeze_time("2020-01-04T13:01:01Z"):
                response = self.client.get(
                    f"/api/projects/{self.team.id}/events/?properties=%s"
                    % (json.dumps([{"key": "id", "value": cohort1.id, "type": "cohort"}]))
                ).json()

        self.assertEqual(len(response["results"]), 2)

    def test_filter_by_person(self):
        person = _create_person(
            properties={"email": "tim@posthog.com"},
            distinct_ids=["2", "some-random-uid"],
            team=self.team,
            immediate=True,
        )

        _create_event(event="random event", team=self.team, distinct_id="2", properties={"$ip": "8.8.8.8"})
        _create_event(
            event="random event", team=self.team, distinct_id="some-random-uid", properties={"$ip": "8.8.8.8"}
        )
        _create_event(event="random event", team=self.team, distinct_id="some-other-one", properties={"$ip": "8.8.8.8"})
        flush_persons_and_events()

        response = self.client.get(f"/api/projects/{self.team.id}/events/?person_id={person.pk}").json()
        self.assertEqual(len(response["results"]), 2)
        self.assertEqual(response["results"][0]["elements"], [])

    def test_filter_by_nonexisting_person(self):
        response = self.client.get(f"/api/projects/{self.team.id}/events/?person_id=5555555555")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 0)

    def test_custom_event_values(self):
        events = ["test", "new event", "another event"]
        for event in events:
            _create_event(
                distinct_id="bla",
                event=event,
                team=self.team,
                properties={"random_prop": "don't include", "some other prop": "with some text"},
            )
        response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=custom_event").json()
        self.assertListEqual(sorted(events), sorted(event["name"] for event in response))

    @test_with_materialized_columns(["random_prop"])
    @snapshot_clickhouse_queries
    def test_event_property_values(self):

        with freeze_time("2020-01-10"):
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "don't include", "some other prop": "with some text"},
            )

        with freeze_time("2020-01-20 20:00:00"):
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "asdf", "some other prop": "with some text"},
            )
            _create_event(distinct_id="bla", event="random event", team=self.team, properties={"random_prop": "asdf"})
            _create_event(distinct_id="bla", event="random event", team=self.team, properties={"random_prop": "qwerty"})
            _create_event(distinct_id="bla", event="random event", team=self.team, properties={"random_prop": True})
            _create_event(distinct_id="bla", event="random event", team=self.team, properties={"random_prop": False})
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": {"first_name": "Mary", "last_name": "Smith"}},
            )
            _create_event(
                distinct_id="bla", event="random event", team=self.team, properties={"something_else": "qwerty"}
            )
            _create_event(distinct_id="bla", event="random event", team=self.team, properties={"random_prop": 565})
            _create_event(
                distinct_id="bla", event="random event", team=self.team, properties={"random_prop": ["item1", "item2"]},
            )
            _create_event(
                distinct_id="bla", event="random event", team=self.team, properties={"random_prop": ["item3"]}
            )

            team2 = Organization.objects.bootstrap(None)[2]
            _create_event(distinct_id="bla", event="random event", team=team2, properties={"random_prop": "abcd"})
            response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=random_prop").json()

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

            response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=random_prop&value=qw").json()
            self.assertEqual(response[0]["name"], "qwerty")

            response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=random_prop&value=QW").json()
            self.assertEqual(response[0]["name"], "qwerty")

            response = self.client.get(f"/api/projects/{self.team.id}/events/values/?key=random_prop&value=6").json()
            self.assertEqual(response[0]["name"], "565")

    def test_before_and_after(self):
        user = self._create_user("tim")
        self.client.force_login(user)
        _create_person(
            properties={"email": "tim@posthog.com"}, team=self.team, distinct_ids=["2", "some-random-uid"],
        )

        with freeze_time("2020-01-10"):
            event1_uuid = _create_event(team=self.team, event="sign up", distinct_id="2")
        with freeze_time("2020-01-8"):
            event2_uuid = _create_event(team=self.team, event="sign up", distinct_id="2")
        with freeze_time("2020-01-7"):
            event3_uuid = _create_event(team=self.team, event="random other event", distinct_id="2")

        action = Action.objects.create(team=self.team)
        ActionStep.objects.create(action=action, event="sign up")

        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?after=2020-01-09T00:00:00.000Z&action_id=%s" % action.pk
        ).json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["id"], event1_uuid)

        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?before=2020-01-09T00:00:00.000Z&action_id=%s" % action.pk
        ).json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["id"], event2_uuid)

        # without action
        response = self.client.get(f"/api/projects/{self.team.id}/events/?after=2020-01-09T00:00:00.000Z").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["id"], event1_uuid)

        response = self.client.get(f"/api/projects/{self.team.id}/events/?before=2020-01-09T00:00:00.000Z").json()
        self.assertEqual(len(response["results"]), 2)
        self.assertEqual(response["results"][0]["id"], event2_uuid)
        self.assertEqual(response["results"][1]["id"], event3_uuid)

    def test_pagination(self):
        with freeze_time("2021-10-10T12:03:03.829294Z"):
            _create_person(team=self.team, distinct_ids=["1"])
            for idx in range(0, 250):
                _create_event(
                    team=self.team,
                    event="some event",
                    distinct_id="1",
                    timestamp=timezone.now() - relativedelta(months=11) + relativedelta(days=idx, seconds=idx),
                )
            response = self.client.get(f"/api/projects/{self.team.id}/events/?distinct_id=1").json()
            self.assertEqual(len(response["results"]), 100)
            self.assertIn(
                f"http://testserver/api/projects/{self.team.id}/events/?distinct_id=1&before=",
                unquote(response["next"]),
            )
            response = self.client.get(f"/api/projects/{self.team.id}/events/?distinct_id=1").json()
            self.assertEqual(len(response["results"]), 100)
            self.assertIn(
                f"http://testserver/api/projects/{self.team.id}/events/?distinct_id=1&before=",
                unquote(response["next"]),
            )

            page2 = self.client.get(response["next"]).json()

            from posthog.client import sync_execute

            self.assertEqual(
                sync_execute("select count(*) from events where team_id = %(team_id)s", {"team_id": self.team.pk})[0][
                    0
                ],
                250,
            )

            self.assertEqual(len(page2["results"]), 100)
            self.assertEqual(
                unquote(page2["next"]),
                f"http://testserver/api/projects/{self.team.id}/events/?distinct_id=1&before=2020-12-30T12:03:53.829294+00:00",
            )

            page3 = self.client.get(page2["next"]).json()
            self.assertEqual(len(page3["results"]), 50)
            self.assertIsNone(page3["next"])

    def test_pagination_bounded_date_range(self):
        with freeze_time("2021-10-10T12:03:03.829294Z"):
            _create_person(team=self.team, distinct_ids=["1"])
            now = timezone.now() - relativedelta(months=11)
            after = (now).astimezone(pytz.utc).isoformat()
            before = (now + relativedelta(days=23)).astimezone(pytz.utc).isoformat()
            params = {"distinct_id": "1", "after": after, "before": before, "limit": 10}
            params_string = urlencode(params)
            for idx in range(0, 25):
                _create_event(
                    team=self.team,
                    event="some event",
                    distinct_id="1",
                    timestamp=now + relativedelta(days=idx, seconds=-idx),
                )
            response = self.client.get(f"/api/projects/{self.team.id}/events/?{params_string}").json()
            self.assertEqual(len(response["results"]), 10)
            self.assertIn("before=", unquote(response["next"]))
            self.assertIn(f"after={after}", unquote(response["next"]))

            params = {
                "distinct_id": "1",
                "after": after,
                "before": before,
                "limit": 10,
            }
            params_string = urlencode(params)

            response = self.client.get(f"/api/projects/{self.team.id}/events/?{params_string}").json()
            self.assertEqual(len(response["results"]), 10)
            self.assertIn(f"before=", unquote(response["next"]))
            self.assertIn(f"after={after}", unquote(response["next"]))

            page2 = self.client.get(response["next"]).json()

            from posthog.client import sync_execute

            self.assertEqual(
                sync_execute("select count(*) from events where team_id = %(team_id)s", {"team_id": self.team.pk})[0][
                    0
                ],
                25,
            )

            self.assertEqual(len(page2["results"]), 10)
            self.assertIn(f"before=", unquote(page2["next"]))
            self.assertIn(f"after={after}", unquote(page2["next"]))

            page3 = self.client.get(page2["next"]).json()
            self.assertEqual(len(page3["results"]), 3)
            self.assertIsNone(page3["next"])

    def test_ascending_order_timestamp(self):
        for idx in range(10):
            _create_event(
                team=self.team,
                event="some event",
                distinct_id="1",
                timestamp=timezone.now() - relativedelta(months=11) + relativedelta(days=idx, seconds=idx),
            )

        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?distinct_id=1&orderBy={json.dumps(['timestamp'])}"
        ).json()
        self.assertEqual(len(response["results"]), 10)
        self.assertLess(
            parser.parse(response["results"][0]["timestamp"]), parser.parse(response["results"][-1]["timestamp"])
        )

    def test_default_descending_order_timestamp(self):
        for idx in range(10):
            _create_event(
                team=self.team,
                event="some event",
                distinct_id="1",
                timestamp=timezone.now() - relativedelta(months=11) + relativedelta(days=idx, seconds=idx),
            )

        response = self.client.get(f"/api/projects/{self.team.id}/events/?distinct_id=1").json()
        self.assertEqual(len(response["results"]), 10)
        self.assertGreater(
            parser.parse(response["results"][0]["timestamp"]), parser.parse(response["results"][-1]["timestamp"])
        )

    def test_action_no_steps(self):
        action = Action.objects.create(team=self.team)

        response = self.client.get(f"/api/projects/{self.team.id}/events/?action_id=%s" % action.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 0)

    def test_get_single_action(self):
        event1_uuid = _create_event(team=self.team, event="sign up", distinct_id="2", properties={"key": "test_val"})
        response = self.client.get(f"/api/projects/{self.team.id}/events/%s/" % event1_uuid)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["event"], "sign up")
        self.assertEqual(response.json()["properties"], {"key": "test_val"})

    def test_events_in_future(self):
        with freeze_time("2012-01-15T04:01:34.000Z"):
            _create_event(team=self.team, event="5th action", distinct_id="2", properties={"$os": "Windows 95"})
        # Don't show events more than 5 seconds in the future
        with freeze_time("2012-01-15T04:01:44.000Z"):
            _create_event(team=self.team, event="5th action", distinct_id="2", properties={"$os": "Windows 95"})
        with freeze_time("2012-01-15T04:01:34.000Z"):
            response = self.client.get(f"/api/projects/{self.team.id}/events/").json()
        self.assertEqual(len(response["results"]), 1)

    @patch("posthog.api.event.EventViewSet.CSV_EXPORT_MAXIMUM_LIMIT", 10)
    def test_events_csv_export_with_param_limit(self):
        with freeze_time("2012-01-15T04:01:34.000Z"):
            for _ in range(12):
                _create_event(team=self.team, event="5th action", distinct_id="2", properties={"$os": "Windows 95"})
            response = self.client.get(f"/api/projects/{self.team.id}/events.csv?limit=5")
        self.assertEqual(
            len(response.content.splitlines()), 6, "CSV export should return up to limit=5 events (+ headers row)",
        )

    @patch("posthog.api.event.EventViewSet.CSV_EXPORT_DEFAULT_LIMIT", 10)
    def test_events_csv_export_default_limit(self):
        with freeze_time("2012-01-15T04:01:34.000Z"):
            for _ in range(12):
                _create_event(team=self.team, event="5th action", distinct_id="2", properties={"$os": "Windows 95"})
            response = self.client.get(f"/api/projects/{self.team.id}/events.csv")
        self.assertEqual(
            len(response.content.splitlines()),
            11,
            "CSV export should return up to CSV_EXPORT_MAXIMUM_LIMIT events (+ headers row)",
        )

    @patch("posthog.api.event.EventViewSet.CSV_EXPORT_MAXIMUM_LIMIT", 10)
    def test_events_csv_export_maximum_limit(self):
        with freeze_time("2012-01-15T04:01:34.000Z"):
            for _ in range(12):
                _create_event(team=self.team, event="5th action", distinct_id="2", properties={"$os": "Windows 95"})
            response = self.client.get(f"/api/projects/{self.team.id}/events.csv")
        self.assertEqual(
            len(response.content.splitlines()),
            11,
            "CSV export should return up to CSV_EXPORT_MAXIMUM_LIMIT events (+ headers row)",
        )

    @patch("posthog.api.event.EventViewSet.CSV_EXPORT_MAXIMUM_LIMIT", 10)
    def test_events_csv_export_over_maximum_limit(self):
        with freeze_time("2012-01-15T04:01:34.000Z"):
            for _ in range(12):
                _create_event(team=self.team, event="5th action", distinct_id="2", properties={"$os": "Windows 95"})
            response = self.client.get(f"/api/projects/{self.team.id}/events.csv?limit=100")
        self.assertEqual(
            len(response.content.splitlines()),
            11,
            "CSV export should return up to CSV_EXPORT_MAXIMUM_LIMIT events (+ headers row)",
        )

    def test_get_event_by_id(self):
        _create_person(
            properties={"email": "someone@posthog.com"}, team=self.team, distinct_ids=["1"], is_identified=True,
        )
        event_id = _create_event(team=self.team, event="event", distinct_id="1", timestamp=timezone.now())

        response = self.client.get(f"/api/projects/{self.team.id}/events/{event_id}",)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["event"], "event")
        self.assertIsNone(response_json["person"])

        with_person_response = self.client.get(f"/api/projects/{self.team.id}/events/{event_id}?include_person=true",)
        self.assertEqual(with_person_response.status_code, status.HTTP_200_OK)
        with_person_response_json = with_person_response.json()
        self.assertEqual(with_person_response_json["event"], "event")
        self.assertIsNotNone(with_person_response_json["person"])

        response = self.client.get(f"/api/projects/{self.team.id}/events/123456",)
        # EE will inform the user the ID passed is not a valid UUID
        self.assertIn(response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_400_BAD_REQUEST])

        response = self.client.get(f"/api/projects/{self.team.id}/events/im_a_string_not_an_integer",)
        self.assertIn(response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_400_BAD_REQUEST])

    def test_limit(self):
        _create_person(
            properties={"email": "tim@posthog.com"},
            team=self.team,
            distinct_ids=["2", "some-random-uid"],
            is_identified=True,
        )

        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="2",
            properties={"$ip": "8.8.8.8"},
            elements=[Element(tag_name="button", text="something"), Element(tag_name="div")],
        )
        _create_event(event="$pageview", team=self.team, distinct_id="some-random-uid", properties={"$ip": "8.8.8.8"})
        _create_event(event="$pageview", team=self.team, distinct_id="some-other-one", properties={"$ip": "8.8.8.8"})

        response = self.client.get(f"/api/projects/{self.team.id}/events/?limit=1").json()
        self.assertEqual(1, len(response["results"]))

        response = self.client.get(f"/api/projects/{self.team.id}/events/?limit=2").json()
        self.assertEqual(2, len(response["results"]))

    def test_get_events_with_specified_token(self):
        _, _, user2 = User.objects.bootstrap("Test", "team2@posthog.com", None)
        assert user2.team is not None
        assert self.team is not None

        self.assertNotEqual(user2.team.id, self.team.id)

        event1_uuid = _create_event(team=self.team, event="sign up", distinct_id="2", properties={"key": "test_val"})
        event2_uuid = _create_event(team=user2.team, event="sign up", distinct_id="2", properties={"key": "test_val"})

        response_team1 = self.client.get(f"/api/projects/{self.team.id}/events/{event1_uuid}/")
        response_team1_token = self.client.get(
            f"/api/projects/{self.team.id}/events/{event1_uuid}/", data={"token": self.team.api_token}
        )

        response_team2_event1 = self.client.get(
            f"/api/projects/{self.team.id}/events/{event1_uuid}/", data={"token": user2.team.api_token}
        )

        # The feature being tested here is usually used with personal API token auth,
        # but logging in works the same way and is more to the point in the test
        self.client.force_login(user2)

        response_team2_event2 = self.client.get(
            f"/api/projects/{self.team.id}/events/{event2_uuid}/", data={"token": user2.team.api_token}
        )

        self.assertEqual(response_team1.status_code, status.HTTP_200_OK)
        self.assertEqual(response_team1_token.status_code, status.HTTP_200_OK)
        self.assertEqual(response_team1.json(), response_team1_token.json())
        self.assertNotEqual(response_team1.json(), response_team2_event2.json())
        self.assertEqual(response_team2_event1.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response_team2_event2.status_code, status.HTTP_200_OK)

        response_invalid_token = self.client.get(f"/api/projects/{self.team.id}/events?token=invalid")
        self.assertEqual(response_invalid_token.status_code, 401)

    @patch("posthog.api.event.query_with_columns")
    def test_optimize_query(self, patch_query_with_columns):
        #  For ClickHouse we normally only query the last day,
        # but if a user doesn't have many events we still want to return events that are older
        patch_query_with_columns.return_value = [
            {
                "uuid": "event",
                "event": "d",
                "properties": "{}",
                "timestamp": timezone.now(),
                "team_id": "d",
                "distinct_id": "d",
                "elements_chain": "d",
            }
        ]
        response = self.client.get(f"/api/projects/{self.team.id}/events/").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(patch_query_with_columns.call_count, 2)

        patch_query_with_columns.return_value = [
            {
                "uuid": "event",
                "event": "d",
                "properties": "{}",
                "timestamp": timezone.now(),
                "team_id": "d",
                "distinct_id": "d",
                "elements_chain": "d",
            }
            for _ in range(0, 100)
        ]
        response = self.client.get(f"/api/projects/{self.team.id}/events/").json()
        self.assertEqual(patch_query_with_columns.call_count, 3)

    def test_filter_events_by_being_after_properties_with_date_type(self):
        journeys_for(
            {
                "2": [
                    {
                        "event": "should_be_excluded",
                        "properties": {"prop_that_is_a_unix_timestamp": datetime(2012, 1, 7, 18).timestamp()},
                    },
                    {
                        "event": "should_be_included",
                        "properties": {"prop_that_is_a_unix_timestamp": datetime(2012, 1, 7, 19).timestamp()},
                    },
                    {
                        "event": "should_be_included",
                        "properties": {"prop_that_is_a_unix_timestamp": datetime(2012, 1, 7, 20).timestamp()},
                    },
                ]
            },
            self.team,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?properties=%s"
            % (
                json.dumps(
                    [
                        {
                            "key": "prop_that_is_a_unix_timestamp",
                            "value": "2012-01-07 18:30:00",
                            "operator": "is_date_after",
                            "type": "event",
                        }
                    ]
                )
            )
        ).json()

        self.assertEqual(len(response["results"]), 2)
        self.assertEqual([r["event"] for r in response["results"]], ["should_be_included", "should_be_included"])

    def test_filter_events_by_being_before_properties_with_date_type(self):
        journeys_for(
            {
                "2": [
                    {
                        "event": "should_be_included",
                        "properties": {"prop_that_is_a_unix_timestamp": datetime(2012, 1, 7, 18).timestamp()},
                    },
                    {
                        "event": "should_be_excluded",
                        "properties": {"prop_that_is_a_unix_timestamp": datetime(2012, 1, 7, 19).timestamp()},
                    },
                    {
                        "event": "should_be_excluded",
                        "properties": {"prop_that_is_a_unix_timestamp": datetime(2012, 1, 7, 20).timestamp()},
                    },
                ]
            },
            self.team,
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?properties=%s"
            % (
                json.dumps(
                    [
                        {
                            "key": "prop_that_is_a_unix_timestamp",
                            "value": "2012-01-07 18:30:00",
                            "operator": "is_date_before",
                            "type": "event",
                        }
                    ]
                )
            )
        ).json()

        self.assertEqual(len(response["results"]), 1)
        self.assertEqual([r["event"] for r in response["results"]], ["should_be_included"])

    def test_filter_events_with_date_format(self):
        journeys_for(
            {
                "2": [
                    {
                        "event": "should_be_included",
                        "properties": {"prop_that_is_an_sdk_style_unix_timestamp": 1639427152.339},
                    },
                    {
                        "event": "should_be_excluded",
                        "properties": {
                            "prop_that_is_an_sdk_style_unix_timestamp": 1639427152.339 * 2
                        },  # the far future
                    },
                    {
                        "event": "should_be_excluded",
                        "properties": {
                            "prop_that_is_an_sdk_style_unix_timestamp": 1639427152.339 * 2
                        },  # the far future
                    },
                ]
            },
            self.team,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/events/?properties=%s"
            % (
                json.dumps(
                    [
                        {
                            "key": "prop_that_is_an_sdk_style_unix_timestamp",
                            "value": "2021-12-25 12:00:00",
                            "operator": "is_date_before",
                            "type": "event",
                            "property_type": "DateTime",
                            "property_type_format": "unix_timestamp",
                        }
                    ]
                )
            )
        ).json()

        self.assertEqual(len(response["results"]), 1)
        self.assertEqual([r["event"] for r in response["results"]], ["should_be_included"])
