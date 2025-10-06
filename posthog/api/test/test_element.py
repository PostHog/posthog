import json
from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    _create_event,
    _create_person,
    snapshot_postgres_queries,
)

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models import Element, ElementGroup, Organization

expected_autocapture_data_response_results: list[dict] = [
    {
        "count": 3,
        "hash": None,
        "type": "$autocapture",
        "elements": [
            {
                "text": "event 1",
                "tag_name": "a",
                "attr_class": None,
                "href": "https://posthog.com/event-1",
                "attr_id": None,
                "nth_child": 0,
                "nth_of_type": 0,
                "attributes": {},
                "order": 0,
            },
            {
                "text": "event 1",
                "tag_name": "div",
                "attr_class": None,
                "href": "https://posthog.com/event-1",
                "attr_id": None,
                "nth_child": 0,
                "nth_of_type": 0,
                "attributes": {},
                "order": 1,
            },
        ],
    },
    {
        "count": 2,
        "hash": None,
        "type": "$autocapture",
        "elements": [
            {
                "text": "event 2",
                "tag_name": "a",
                "attr_class": None,
                "href": "https://posthog.com/event-2",
                "attr_id": None,
                "nth_child": 0,
                "nth_of_type": 0,
                "attributes": {},
                "order": 0,
            },
            {
                "text": "event 2",
                "tag_name": "div",
                "attr_class": None,
                "href": "https://posthog.com/event-2",
                "attr_id": None,
                "nth_child": 0,
                "nth_of_type": 0,
                "attributes": {},
                "order": 1,
            },
        ],
    },
]

expected_rage_click_data_response_results: list[dict] = [
    {
        "count": 1,
        "hash": None,
        "type": "$rageclick",
        "elements": [
            {
                "text": "event 1",
                "tag_name": "a",
                "attr_class": None,
                "href": "https://posthog.com/event-1",
                "attr_id": None,
                "nth_child": 0,
                "nth_of_type": 0,
                "attributes": {},
                "order": 0,
            },
            {
                "text": "event 1",
                "tag_name": "div",
                "attr_class": None,
                "href": "https://posthog.com/event-1",
                "attr_id": None,
                "nth_child": 0,
                "nth_of_type": 0,
                "attributes": {},
                "order": 1,
            },
        ],
    },
]


class TestElement(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def test_element_automatic_order(self) -> None:
        elements = [
            Element(tag_name="a", href="https://posthog.com/about", text="click here"),
            Element(tag_name="span"),
            Element(tag_name="div"),
        ]
        ElementGroup.objects.create(team=self.team, elements=elements)

        self.assertEqual(elements[0].order, 0)
        self.assertEqual(elements[1].order, 1)
        self.assertEqual(elements[2].order, 2)

    def test_event_property_values(self) -> None:
        _create_event(
            team=self.team,
            distinct_id="test",
            event="$autocapture",
            elements=[Element(tag_name="a", href="https://posthog.com/about", text="click here")],
        )
        team2 = Organization.objects.bootstrap(None)[2]
        _create_event(
            team=team2,
            distinct_id="test",
            event="$autocapture",
            elements=[Element(tag_name="bla")],
        )

        response = self.client.get("/api/element/values/?key=tag_name").json()
        self.assertEqual(response[0]["name"], "a")
        self.assertEqual(len(response), 1)

        response = self.client.get("/api/element/values/?key=text&value=click").json()
        self.assertEqual(response[0]["name"], "click here")
        self.assertEqual(len(response), 1)

    # checking postgres, don't care about person on events
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    @snapshot_postgres_queries
    def test_element_stats_postgres_queries_are_as_expected(self) -> None:
        self._setup_events()

        self.client.get("/api/element/stats/?paginate_response=true").json()

    def test_element_stats_can_filter_by_properties(self) -> None:
        self._setup_events()

        response = self.client.get("/api/element/stats/?paginate_response=true").json()
        assert len(response["results"]) == 3

        properties_filter = json.dumps([{"key": "$current_url", "value": "http://example.com/another_page"}])
        response = self.client.get(f"/api/element/stats/?paginate_response=true&properties={properties_filter}").json()
        self.assertEqual(len(response["results"]), 1)

    def test_element_stats_can_filter_by_hogql(self) -> None:
        self._setup_events()
        properties_filter = json.dumps(
            [
                {
                    "type": "hogql",
                    "key": "like(properties.$current_url, '%another_page%')",
                },
            ]
        )
        response = self.client.get(f"/api/element/stats/?paginate_response=true&properties={properties_filter}").json()
        self.assertEqual(len(response["results"]), 1)

    def test_element_stats_clamps_date_from_to_start_of_day(self) -> None:
        event_start = "2012-01-14T03:21:34.000Z"
        query_time = "2012-01-14T08:21:34.000Z"

        with freeze_time(event_start) as frozen_time:
            elements = [
                Element(
                    tag_name="a",
                    href="https://posthog.com/about",
                    text="click here",
                    order=0,
                ),
                Element(
                    tag_name="div",
                    href="https://posthog.com/about",
                    text="click here",
                    order=1,
                ),
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
            response = self.client.get(f"/api/element/stats/?paginate_response=true&date_from={query_time}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_json = response.json()
            self.assertEqual(response_json["results"][0]["count"], 2)
            self.assertEqual(response_json["results"][0]["elements"][0]["tag_name"], "a")

    def test_element_stats_can_load_all_the_data(self) -> None:
        self._setup_events()

        response = self.client.get(f"/api/element/stats/?paginate_response=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        assert response_json["next"] is None  # loaded all the data, so no next link
        results = response_json["results"]

        assert results == expected_autocapture_data_response_results + expected_rage_click_data_response_results

    def test_element_stats_can_load_only_rageclick_data(self) -> None:
        self._setup_events()

        response = self.client.get(f"/api/element/stats/?paginate_response=true&include=$rageclick")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        assert response_json["next"] is None  # loaded all the data, so no next link
        results = response_json["results"]

        assert results == expected_rage_click_data_response_results

    # no include params is equivalent to autocapture and rageclick
    @parameterized.expand(["&include=$rageclick&include=$autocapture", ""])
    def test_element_stats_can_load_rageclick_and_autocapture_data(self, include_params) -> None:
        self._setup_events()

        response = self.client.get(f"/api/element/stats/?paginate_response=true{include_params}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        assert response_json["next"] is None  # loaded all the data, so no next link
        results = response_json["results"]

        assert results == expected_autocapture_data_response_results + expected_rage_click_data_response_results

    def test_element_stats_obeys_limit_parameter(self) -> None:
        self._setup_events()

        page_one_response = self.client.get(f"/api/element/stats/?paginate_response=true&limit=1")
        self.assertEqual(page_one_response.status_code, status.HTTP_200_OK)

        page_one_response_json = page_one_response.json()
        assert (
            page_one_response_json["next"]
            == "http://testserver/api/element/stats/?paginate_response=true&limit=1&offset=1"
        )
        limit_to_one_results = page_one_response_json["results"]
        assert limit_to_one_results == [expected_autocapture_data_response_results[0]]

        page_two_response = self.client.get(f"/api/element/stats/?paginate_response=true&limit=1&offset=1")
        self.assertEqual(page_two_response.status_code, status.HTTP_200_OK)

        page_two_response_json = page_two_response.json()
        assert (
            page_two_response_json["next"]
            == "http://testserver/api/element/stats/?paginate_response=true&limit=1&offset=2"
        )
        limit_to_one_results_page_two = page_two_response_json["results"]
        assert limit_to_one_results_page_two == [expected_autocapture_data_response_results[1]]

        page_three_response = self.client.get(f"/api/element/stats/?paginate_response=true&limit=1&offset=2")
        self.assertEqual(page_three_response.status_code, status.HTTP_200_OK)

        page_three_response_json = page_three_response.json()
        assert page_three_response_json["next"] is None
        limit_to_one_results_page_three = page_three_response_json["results"]
        assert limit_to_one_results_page_three == [expected_rage_click_data_response_results[0]]

    def test_element_stats_does_not_allow_non_numeric_limit(self) -> None:
        response = self.client.get(f"/api/element/stats/?limit=not-a-number")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_element_stats_does_not_allow_non_numeric_offset(self) -> None:
        response = self.client.get(f"/api/element/stats/?limit=not-a-number")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_element_stats_does_not_allow_unexepcted_include(self) -> None:
        response = self.client.get(f"/api/element/stats/?include=$autocapture&include=$rageclick&include=$pageview")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def _setup_events(self):
        _create_person(distinct_ids=["one"], team=self.team, properties={"email": "one@mail.com"})
        _create_person(distinct_ids=["two"], team=self.team, properties={"email": "two@mail.com"})
        _create_person(
            distinct_ids=["three"],
            team=self.team,
            properties={"email": "three@mail.com"},
        )
        _create_event(
            team=self.team,
            elements=[
                Element(
                    tag_name="a",
                    href="https://posthog.com/event-1",
                    text="event 1",
                    order=0,
                ),
                Element(
                    tag_name="div",
                    href="https://posthog.com/event-1",
                    text="event 1",
                    order=1,
                ),
            ],
            event="$autocapture",
            distinct_id="one",
            properties={"$current_url": "http://example.com/demo"},
        )
        _create_event(
            team=self.team,
            elements=[
                Element(
                    tag_name="a",
                    href="https://posthog.com/event-1",
                    text="event 1",
                    order=0,
                ),
                Element(
                    tag_name="div",
                    href="https://posthog.com/event-1",
                    text="event 1",
                    order=1,
                ),
            ],
            event="$autocapture",
            distinct_id="one",
            properties={"$current_url": "http://example.com/demo"},
        )
        _create_event(
            team=self.team,
            elements=[
                Element(
                    tag_name="a",
                    href="https://posthog.com/event-1",
                    text="event 1",
                    order=0,
                ),
                Element(
                    tag_name="div",
                    href="https://posthog.com/event-1",
                    text="event 1",
                    order=1,
                ),
            ],
            event="$autocapture",
            distinct_id="one",
            properties={"$current_url": "http://example.com/demo"},
        )
        _create_event(
            team=self.team,
            elements=[
                Element(
                    tag_name="a",
                    href="https://posthog.com/event-2",
                    text="event 2",
                    order=0,
                ),
                Element(
                    tag_name="div",
                    href="https://posthog.com/event-2",
                    text="event 2",
                    order=1,
                ),
            ],
            event="$autocapture",
            distinct_id="two",
            properties={"$current_url": "http://example.com/demo"},
        )
        _create_event(
            team=self.team,
            elements=[
                Element(
                    tag_name="a",
                    href="https://posthog.com/event-2",
                    text="event 2",
                    order=0,
                ),
                Element(
                    tag_name="div",
                    href="https://posthog.com/event-2",
                    text="event 2",
                    order=1,
                ),
            ],
            event="$autocapture",
            distinct_id="three",
            properties={"$current_url": "http://example.com/another_page"},
        )
        _create_event(
            team=self.team,
            elements=[
                Element(
                    tag_name="a",
                    href="https://posthog.com/event-1",
                    text="event 1",
                    order=0,
                ),
                Element(
                    tag_name="div",
                    href="https://posthog.com/event-1",
                    text="event 1",
                    order=1,
                ),
            ],
            event="$rageclick",
            distinct_id="one",
            properties={"$current_url": "http://example.com/demo"},
        )
