import json
from uuid import uuid4

from django.core.cache import cache

from ee.clickhouse.models.event import create_event
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.person import Person
from posthog.test.base import APIBaseTest


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid, uuid=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestClickhousePaths(ClickhouseTestMixin, APIBaseTest):
    def test_insight_paths_basic(self):
        _create_person(team=self.team, distinct_ids=["person_1"])
        _create_event(
            properties={"$current_url": "/"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about"}, distinct_id="person_1", event="$pageview", team=self.team,
        )

        response = self.client.get("/api/insight/path",).json()
        self.assertEqual(len(response["result"]), 1)

    def test_backwards_compatible_path_types(self):

        _create_person(team=self.team, distinct_ids=["person_1"])
        _create_event(
            properties={"$current_url": "/"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/something else"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$screen_name": "/screen1"}, distinct_id="person_1", event="$screen", team=self.team,
        )
        _create_event(
            distinct_id="person_1", event="custom1", team=self.team,
        )
        _create_event(
            distinct_id="person_1", event="custom2", team=self.team,
        )
        response = self.client.get("/api/insight/path", data={"path_type": "$pageview", "insight": "PATHS",}).json()
        self.assertEqual(len(response["result"]), 2)

        response = self.client.get("/api/insight/path", data={"path_type": "custom_event", "insight": "PATHS"}).json()
        self.assertEqual(len(response["result"]), 1)
        response = self.client.get("/api/insight/path", data={"path_type": "$screen", "insight": "PATHS"}).json()
        self.assertEqual(len(response["result"]), 0)

    def test_backwards_compatible_start_point(self):

        _create_person(team=self.team, distinct_ids=["person_1"])
        _create_event(
            properties={"$current_url": "/"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/something else"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$screen_name": "/screen1"}, distinct_id="person_1", event="$screen", team=self.team,
        )
        _create_event(
            properties={"$screen_name": "/screen2"}, distinct_id="person_1", event="$screen", team=self.team,
        )
        _create_event(
            distinct_id="person_1", event="custom1", team=self.team,
        )
        _create_event(
            distinct_id="person_1", event="custom2", team=self.team,
        )
        response = self.client.get(
            "/api/insight/path", data={"path_type": "$pageview", "insight": "PATHS", "start_point": "/about",}
        ).json()
        self.assertEqual(len(response["result"]), 1)

        response = self.client.get(
            "/api/insight/path", data={"path_type": "custom_event", "insight": "PATHS", "start_point": "custom2",}
        ).json()
        self.assertEqual(len(response["result"]), 0)
        response = self.client.get(
            "/api/insight/path", data={"path_type": "$screen", "insight": "PATHS", "start_point": "/screen1",}
        ).json()
        self.assertEqual(len(response["result"]), 1)

    def test_path_groupings(self):
        _create_person(team=self.team, distinct_ids=["person_1"])
        _create_event(
            properties={"$current_url": "/about_1"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about_2"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/something else"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about3"}, distinct_id="person_1", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about4"}, distinct_id="person_1", event="$pageview", team=self.team,
        )

        _create_person(team=self.team, distinct_ids=["person_2"])
        _create_event(
            properties={"$current_url": "/about_1"}, distinct_id="person_2", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about_2"}, distinct_id="person_2", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/something else"}, distinct_id="person_2", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about3"}, distinct_id="person_2", event="$pageview", team=self.team,
        )
        _create_event(
            properties={"$current_url": "/about4"}, distinct_id="person_2", event="$pageview", team=self.team,
        )

        response = self.client.get(
            "/api/insight/path", data={"insight": "PATHS", "path_groupings": json.dumps(["/about%"])}
        ).json()
        self.assertEqual(len(response["result"]), 2)

        response = self.client.get(
            "/api/insight/path", data={"insight": "PATHS", "path_groupings": json.dumps(["/about_%"])}
        ).json()
        self.assertEqual(len(response["result"]), 3)
