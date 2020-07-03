from .base import BaseTest
from posthog.models import Element, ElementGroup, Team, Event
from django.utils.timezone import now
from dateutil.relativedelta import relativedelta

import json


class TestElement(BaseTest):
    TESTS_API = True

    def test_event_property_values(self):
        group = ElementGroup.objects.create(
            team=self.team, elements=[Element(tag_name="a", href="https://posthog.com/about", text="click here")],
        )
        team2 = Team.objects.create()
        ElementGroup.objects.create(team=team2, elements=[Element(tag_name="bla")])
        response = self.client.get("/api/element/values/?key=tag_name").json()
        self.assertEqual(response[0]["name"], "a")
        self.assertEqual(len(response), 1)

        response = self.client.get("/api/element/values/?key=text&value=click").json()
        self.assertEqual(response[0]["name"], "click here")
        self.assertEqual(len(response), 1)

    def test_element_stats(self):
        elements = [
            Element(tag_name="a", href="https://posthog.com/about", text="click here", order=0,),
            Element(tag_name="div", href="https://posthog.com/about", text="click here", order=1,),
        ]
        event1 = Event.objects.create(
            team=self.team,
            elements=elements,
            event="$autocapture",
            properties={"$current_url": "http://example.com/demo"},
        )
        Event.objects.create(
            team=self.team,
            elements=elements,
            event="$autocapture",
            properties={"$current_url": "http://example.com/demo"},
        )
        # make sure we only load last 7 days by default
        Event.objects.create(
            timestamp=now() - relativedelta(days=8),
            team=self.team,
            elements=elements,
            event="$autocapture",
            properties={"$current_url": "http://example.com/demo"},
        )

        Event.objects.create(
            team=self.team,
            event="$autocapture",
            properties={"$current_url": "http://example.com/something_else"},
            elements=[Element(tag_name="img", order=0)],
        )

        with self.assertNumQueries(6):
            response = self.client.get("/api/element/stats/").json()
        self.assertEqual(response[0]["count"], 2)
        self.assertEqual(response[0]["hash"], event1.elements_hash)
        self.assertEqual(response[0]["elements"][0]["tag_name"], "a")
        self.assertEqual(response[1]["count"], 1)

        response = self.client.get(
            "/api/element/stats/?properties=%s"
            % json.dumps([{"key": "$current_url", "value": "http://example.com/demo"}])
        ).json()
