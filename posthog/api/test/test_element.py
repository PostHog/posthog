import json
from typing import Callable

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now

from posthog.models import Element, ElementGroup, Event, Organization
from posthog.test.base import APIBaseTest


def factory_test_element(create_event: Callable) -> Callable:
    class TestElement(APIBaseTest):
        def test_element_automatic_order(self):
            elements = [
                Element(tag_name="a", href="https://posthog.com/about", text="click here"),
                Element(tag_name="span"),
                Element(tag_name="div"),
            ]
            ElementGroup.objects.create(team=self.team, elements=elements)

            self.assertEqual(elements[0].order, 0)
            self.assertEqual(elements[1].order, 1)
            self.assertEqual(elements[2].order, 2)

        def test_event_property_values(self):
            create_event(
                team=self.team,
                distinct_id="test",
                event="$autocapture",
                elements=[Element(tag_name="a", href="https://posthog.com/about", text="click here")],
            )
            team2 = Organization.objects.bootstrap(None)[2]
            create_event(team=team2, distinct_id="test", event="$autocapture", elements=[Element(tag_name="bla")])
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
            event1 = create_event(
                team=self.team,
                elements=elements,
                event="$autocapture",
                distinct_id="test",
                properties={"$current_url": "http://example.com/demo"},
            )
            create_event(
                team=self.team,
                elements=elements,
                event="$autocapture",
                distinct_id="test",
                properties={"$current_url": "http://example.com/demo"},
            )
            # make sure we only load last 7 days by default
            create_event(
                timestamp=now() - relativedelta(days=8),
                team=self.team,
                elements=elements,
                event="$autocapture",
                distinct_id="test",
                properties={"$current_url": "http://example.com/demo"},
            )

            create_event(
                team=self.team,
                event="$autocapture",
                distinct_id="test",
                properties={"$current_url": "http://example.com/something_else"},
                elements=[Element(tag_name="img")],
            )

            with self.assertNumQueries(7):
                # Django session, PostHog user, PostHog team, PostHog org membership, PostHog event aggregated,
                # PostHog element group, PostHog element
                response = self.client.get("/api/element/stats/").json()
            self.assertEqual(response[0]["count"], 2)
            self.assertEqual(response[0]["hash"], event1.elements_hash)
            self.assertEqual(response[0]["elements"][0]["tag_name"], "a")
            self.assertEqual(response[1]["count"], 1)

            response = self.client.get(
                "/api/element/stats/?properties=%s"
                % json.dumps([{"key": "$current_url", "value": "http://example.com/demo"}])
            ).json()
            self.assertEqual(len(response), 1)

    return TestElement


class TestElement(factory_test_element(Event.objects.create)):  # type: ignore
    pass
