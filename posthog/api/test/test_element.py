import json
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time
from rest_framework import status

from posthog.models import Element, ElementGroup, Organization
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person


class TestElement(ClickhouseTestMixin, APIBaseTest):
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
        _create_event(
            team=self.team,
            distinct_id="test",
            event="$autocapture",
            elements=[Element(tag_name="a", href="https://posthog.com/about", text="click here")],
        )
        team2 = Organization.objects.bootstrap(None)[2]
        _create_event(team=team2, distinct_id="test", event="$autocapture", elements=[Element(tag_name="bla")])

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

        _create_person(
            team=self.team, distinct_ids=["test"],
        )
        _create_event(
            team=self.team,
            elements=elements,
            event="$autocapture",
            distinct_id="test",
            properties={"$current_url": "http://example.com/demo"},
        )
        _create_event(
            team=self.team,
            elements=elements,
            event="$autocapture",
            distinct_id="test",
            properties={"$current_url": "http://example.com/demo"},
        )

        # make sure we only load last 7 days by default
        _create_event(
            timestamp=now() - relativedelta(days=8),
            team=self.team,
            elements=elements,
            event="$autocapture",
            distinct_id="test",
            properties={"$current_url": "http://example.com/demo"},
        )

        _create_event(
            team=self.team,
            event="$autocapture",
            distinct_id="test",
            properties={"$current_url": "http://example.com/something_else"},
            elements=[Element(tag_name="img")],
        )

        with self.assertNumQueries(6):
            # Django session, PostHog user, PostHog team, PostHog org membership
            # then 2 for inserting person in test setup
            response = self.client.get("/api/element/stats/").json()
        self.assertEqual(response[0]["count"], 2)
        self.assertEqual(response[0]["elements"][0]["tag_name"], "a")
        self.assertEqual(response[1]["count"], 1)

        response = self.client.get(
            "/api/element/stats/?properties=%s"
            % json.dumps([{"key": "$current_url", "value": "http://example.com/demo"}])
        ).json()
        self.assertEqual(len(response), 1)

    def test_element_stats_clamps_date_from_to_start_of_day(self):
        event_start = "2012-01-14T03:21:34.000Z"
        query_time = "2012-01-14T08:21:34.000Z"

        with freeze_time(event_start) as frozen_time:
            elements = [
                Element(tag_name="a", href="https://posthog.com/about", text="click here", order=0,),
                Element(tag_name="div", href="https://posthog.com/about", text="click here", order=1,),
            ]

            _create_event(  # 3 am but included because date_from is set to start of day
                timestamp=frozen_time(),
                team=self.team,
                elements=elements,
                event="$autocapture",
                distinct_id="test",
                properties={"$current_url": "http://example.com/demo"},
            )

            frozen_time.tick(delta=timedelta(hours=10))

            _create_event(  # included
                timestamp=frozen_time(),
                team=self.team,
                elements=elements,
                event="$autocapture",
                distinct_id="test",
                properties={"$current_url": "http://example.com/demo"},
            )

        with freeze_time(query_time):
            # the UI doesn't allow you to choose time, so query should always be from start of day
            response = self.client.get(f"/api/element/stats/?date_from={query_time}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_json = response.json()
            self.assertEqual(response_json[0]["count"], 2)
            self.assertEqual(response_json[0]["elements"][0]["tag_name"], "a")
