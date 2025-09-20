import json
import urllib.parse

from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import patch

from posthog.clickhouse.client import sync_execute
from posthog.models.cohort import Cohort
from posthog.models.person import Person
from posthog.tasks.calculate_cohort import insert_cohort_from_insight_filter
from posthog.tasks.test.test_calculate_cohort import calculate_cohort_test_factory


class TestClickhouseCalculateCohort(ClickhouseTestMixin, calculate_cohort_test_factory(_create_event, _create_person)):  # type: ignore
    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_insight_filter.delay")
    def test_create_stickiness_cohort(self, _insert_cohort_from_insight_filter):
        _create_person(team_id=self.team.pk, distinct_ids=["blabla"])
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="blabla",
            properties={"$math_prop": 1},
            timestamp="2021-01-01T12:00:00Z",
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/?insight=STICKINESS&properties=%5B%5D&interval=day&display=ActionsLineGraph&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%5D&shown_as=Stickiness&date_from=2021-01-01&entity_id=%24pageview&entity_type=events&stickiness_days=1&label=%24pageview",
            {"name": "test", "is_static": True},
        ).json()

        cohort_id = response["id"]

        _insert_cohort_from_insight_filter.assert_called_once_with(
            cohort_id,
            {
                "insight": "STICKINESS",
                "properties": "[]",
                "interval": "day",
                "display": "ActionsLineGraph",
                "events": '[{"id":"$pageview","name":"$pageview","type":"events","order":0}]',
                "shown_as": "Stickiness",
                "date_from": "2021-01-01",
                "entity_id": "$pageview",
                "entity_type": "events",
                "stickiness_days": "1",
                "label": "$pageview",
            },
            self.team.pk,
        )

        insert_cohort_from_insight_filter(
            cohort_id,
            {
                "date_from": "2021-01-01",
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "custom_name": None,
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    }
                ],
                "insight": "STICKINESS",
                "interval": "day",
                "selected_interval": 1,
                "shown_as": "Stickiness",
                "entity_id": "$pageview",
                "entity_type": "events",
                "entity_math": None,
            },
        )
        cohort = Cohort.objects.get(pk=cohort_id)
        people = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(people.count(), 1)
        self.assertEqual(cohort.count, 1)

    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_insight_filter.delay")
    def test_create_trends_cohort(self, _insert_cohort_from_insight_filter):
        _create_person(team_id=self.team.pk, distinct_ids=["blabla"])
        with freeze_time("2021-01-01 00:06:34"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="blabla",
                properties={"$math_prop": 1},
                timestamp="2021-01-01T12:00:00Z",
            )

        with freeze_time("2021-01-02 00:06:34"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="blabla",
                properties={"$math_prop": 4},
                timestamp="2021-01-01T12:00:00Z",
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/?interval=day&display=ActionsLineGraph&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%5D&properties=%5B%5D&entity_id=%24pageview&entity_type=events&date_from=2021-01-01&date_to=2021-01-01&label=%24pageview",
            {"name": "test", "is_static": True},
        ).json()
        cohort_id = response["id"]
        _insert_cohort_from_insight_filter.assert_called_once_with(
            cohort_id,
            {
                "interval": "day",
                "display": "ActionsLineGraph",
                "events": '[{"id":"$pageview","name":"$pageview","type":"events","order":0}]',
                "properties": "[]",
                "entity_id": "$pageview",
                "entity_type": "events",
                "date_from": "2021-01-01",
                "date_to": "2021-01-01",
                "label": "$pageview",
            },
            self.team.pk,
        )
        insert_cohort_from_insight_filter(
            cohort_id,
            {
                "date_from": "2021-01-01",
                "date_to": "2021-01-01",
                "display": "ActionsLineGraph",
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    }
                ],
                "entity_id": "$pageview",
                "entity_type": "events",
                "insight": "TRENDS",
                "interval": "day",
            },
        )
        cohort = Cohort.objects.get(pk=cohort_id)
        people = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(cohort.errors_calculating, 0)
        self.assertEqual(
            people.count(),
            1,
            {
                "a": sync_execute(
                    "select person_id from person_static_cohort where team_id = {} and cohort_id = {} ".format(
                        self.team.id, cohort.pk
                    )
                ),
                "b": sync_execute(
                    "select person_id from person_static_cohort FINAL where team_id = {} and cohort_id = {} ".format(
                        self.team.id, cohort.pk
                    )
                ),
            },
        )
        self.assertEqual(cohort.count, 1)

    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_insight_filter.delay")
    def test_create_trends_cohort_arg_test(self, _insert_cohort_from_insight_filter):
        # prior to 8124, subtitute parameters was called on insight cohorting which caused '%' in LIKE arguments to be interepreted as a missing parameter

        _create_person(team_id=self.team.pk, distinct_ids=["blabla"])
        with freeze_time("2021-01-01 00:06:34"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="blabla",
                properties={"$domain": "https://app.posthog.com/123"},
                timestamp="2021-01-01T12:00:00Z",
            )

        with freeze_time("2021-01-02 00:06:34"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="blabla",
                properties={"$domain": "https://app.posthog.com/123"},
                timestamp="2021-01-01T12:00:00Z",
            )

        params = {
            "date_from": "2021-01-01",
            "date_to": "2021-01-01",
            "display": "ActionsLineGraph",
            "events": json.dumps([{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]),
            "entity_id": "$pageview",
            "entity_type": "events",
            "insight": "TRENDS",
            "interval": "day",
            "properties": json.dumps(
                [
                    {
                        "key": "$domain",
                        "value": "app.posthog.com",
                        "operator": "icontains",
                        "type": "event",
                    }
                ]
            ),
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/?{urllib.parse.urlencode(params)}",
            {"name": "test", "is_static": True},
        ).json()
        cohort_id = response["id"]

        _insert_cohort_from_insight_filter.assert_called_once_with(
            cohort_id,
            {
                "date_from": "2021-01-01",
                "date_to": "2021-01-01",
                "display": "ActionsLineGraph",
                "events": '[{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]',
                "entity_id": "$pageview",
                "entity_type": "events",
                "insight": "TRENDS",
                "interval": "day",
                "properties": '[{"key": "$domain", "value": "app.posthog.com", "operator": "icontains", "type": "event"}]',
            },
            self.team.pk,
        )
        insert_cohort_from_insight_filter(
            cohort_id,
            {
                "date_from": "2021-01-01",
                "date_to": "2021-01-01",
                "display": "ActionsLineGraph",
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "math": None,
                        "math_hogql": None,
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    }
                ],
                "properties": [
                    {
                        "key": "$domain",
                        "value": "app.posthog.com",
                        "operator": "icontains",
                        "type": "event",
                    }
                ],
                "entity_id": "$pageview",
                "entity_type": "events",
                "insight": "TRENDS",
                "interval": "day",
            },
        )
        cohort = Cohort.objects.get(pk=cohort_id)
        people = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(cohort.errors_calculating, 0)
        self.assertEqual(
            people.count(),
            1,
            {
                "a": sync_execute(
                    "select person_id from person_static_cohort where team_id = {} and cohort_id = {} ".format(
                        self.team.id, cohort.pk
                    )
                ),
                "b": sync_execute(
                    "select person_id from person_static_cohort FINAL where team_id = {} and cohort_id = {} ".format(
                        self.team.id, cohort.pk
                    )
                ),
            },
        )
        self.assertEqual(cohort.count, 1)

    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_insight_filter.delay")
    def test_create_funnels_cohort(self, _insert_cohort_from_insight_filter):
        _create_person(team_id=self.team.pk, distinct_ids=["blabla"])
        with freeze_time("2021-01-01 00:06:34"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="blabla",
                properties={"$math_prop": 1},
                timestamp="2021-01-01T12:00:00Z",
            )

        with freeze_time("2021-01-02 00:06:34"):
            _create_event(
                team=self.team,
                event="$another_view",
                distinct_id="blabla",
                properties={"$math_prop": 4},
                timestamp="2021-01-02T12:00:00Z",
            )

        params = {
            "insight": "FUNNELS",
            "events": json.dumps(
                [
                    {
                        "id": "$pageview",
                        "math": None,
                        "name": "$pageview",
                        "type": "events",
                        "order": 0,
                        "properties": [],
                        "math_hogql": None,
                        "math_property": None,
                    },
                    {
                        "id": "$another_view",
                        "math": None,
                        "name": "$another_view",
                        "type": "events",
                        "order": 1,
                        "properties": [],
                        "math_hogql": None,
                        "math_property": None,
                    },
                ]
            ),
            "display": "FunnelViz",
            "interval": "day",
            "layout": "horizontal",
            "date_from": "2021-01-01",
            "date_to": "2021-01-07",
            "funnel_step": 1,
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/?{urllib.parse.urlencode(params)}",
            {"name": "test", "is_static": True},
        ).json()

        cohort_id = response["id"]

        _insert_cohort_from_insight_filter.assert_called_once_with(
            cohort_id,
            {
                "insight": "FUNNELS",
                "events": '[{"id": "$pageview", "math": null, "name": "$pageview", "type": "events", "order": 0, "properties": [], "math_hogql": null, "math_property": null}, {"id": "$another_view", "math": null, "name": "$another_view", "type": "events", "order": 1, "properties": [], "math_hogql": null, "math_property": null}]',
                "display": "FunnelViz",
                "interval": "day",
                "layout": "horizontal",
                "date_from": "2021-01-01",
                "date_to": "2021-01-07",
                "funnel_step": "1",
            },
            self.team.pk,
        )

        insert_cohort_from_insight_filter(cohort_id, params)

        cohort = Cohort.objects.get(pk=cohort_id)
        people = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(cohort.errors_calculating, 0)
        self.assertEqual(people.count(), 1)
        self.assertEqual(cohort.count, 1)

    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_insight_filter.delay")
    def test_create_lifecycle_cohort(self, _insert_cohort_from_insight_filter):
        def _create_events(data, event="$pageview"):
            person_result = []
            for id, timestamps in data:
                with freeze_time(timestamps[0]):
                    person_result.append(
                        _create_person(
                            team_id=self.team.pk,
                            distinct_ids=[id],
                            properties={
                                "name": id,
                                **({"email": "test@posthog.com"} if id == "p1" else {}),
                            },
                        )
                    )
                for timestamp in timestamps:
                    _create_event(team=self.team, event=event, distinct_id=id, timestamp=timestamp)
            return person_result

        people = _create_events(
            data=[
                (
                    "p1",
                    [
                        "2020-01-11T12:00:00Z",
                        "2020-01-12T12:00:00Z",
                        "2020-01-13T12:00:00Z",
                        "2020-01-15T12:00:00Z",
                        "2020-01-17T12:00:00Z",
                        "2020-01-19T12:00:00Z",
                    ],
                ),
                ("p2", ["2020-01-09T12:00:00Z", "2020-01-12T12:00:00Z"]),
                ("p3", ["2020-01-12T12:00:00Z"]),
                ("p4", ["2020-01-15T12:00:00Z"]),
            ]
        )

        query_params = {
            "date_from": "2020-01-12T00:00:00Z",
            "date_to": "2020-01-19T00:00:00Z",
            "events": json.dumps([{"id": "$pageview", "type": "events", "order": 0}]),
            "insight": "LIFECYCLE",
            "interval": "day",
            "shown_as": "Lifecycle",
            "smoothing_intervals": 1,
            "entity_id": "$pageview",
            "entity_type": "events",
            "entity_math": "total",
            "target_date": "2020-01-13",
            "entity_order": 0,
            "lifecycle_type": "returning",
        }

        response = self.client.post(
            f"/api/cohort/?{urllib.parse.urlencode(query_params)}",
            data={"is_static": True, "name": "lifecycle_static_cohort_returning"},
        ).json()
        cohort_id = response["id"]

        _insert_cohort_from_insight_filter.assert_called_once_with(
            cohort_id,
            {
                "date_from": "2020-01-12T00:00:00Z",
                "date_to": "2020-01-19T00:00:00Z",
                "events": '[{"id": "$pageview", "type": "events", "order": 0}]',
                "insight": "LIFECYCLE",
                "interval": "day",
                "shown_as": "Lifecycle",
                "smoothing_intervals": "1",
                "entity_id": "$pageview",
                "entity_type": "events",
                "entity_math": "total",
                "target_date": "2020-01-13",
                "entity_order": "0",
                "lifecycle_type": "returning",
            },
            self.team.pk,
        )

        insert_cohort_from_insight_filter(
            cohort_id,
            {
                "date_from": "2020-01-12T00:00:00Z",
                "date_to": "2020-01-19T00:00:00Z",
                "events": [{"id": "$pageview", "type": "events", "order": 0}],
                "insight": "LIFECYCLE",
                "interval": "day",
                "shown_as": "Lifecycle",
                "smoothing_intervals": "1",
                "entity_id": "$pageview",
                "entity_type": "events",
                "entity_math": "total",
                "target_date": "2020-01-13",
                "entity_order": "0",
                "lifecycle_type": "returning",
            },
        )
        cohort = Cohort.objects.get(pk=response["id"])
        people_result = Person.objects.filter(cohort__id=cohort.pk).values_list("id", flat=True)
        self.assertIn(people[0].id, people_result)

        query_params = {
            "date_from": "2020-01-12T00:00:00Z",
            "date_to": "2020-01-19T00:00:00Z",
            "events": json.dumps([{"id": "$pageview", "type": "events", "order": 0}]),
            "insight": "LIFECYCLE",
            "interval": "day",
            "shown_as": "Lifecycle",
            "smoothing_intervals": 1,
            "entity_id": "$pageview",
            "entity_type": "events",
            "entity_math": "total",
            "target_date": "2020-01-13",
            "entity_order": 0,
            "lifecycle_type": "dormant",
        }
        response = self.client.post(
            f"/api/cohort/?{urllib.parse.urlencode(query_params)}",
            data={"is_static": True, "name": "lifecycle_static_cohort_dormant"},
        ).json()
        cohort_id = response["id"]

        _insert_cohort_from_insight_filter.assert_called_with(
            cohort_id,
            {
                "date_from": "2020-01-12T00:00:00Z",
                "date_to": "2020-01-19T00:00:00Z",
                "events": '[{"id": "$pageview", "type": "events", "order": 0}]',
                "insight": "LIFECYCLE",
                "interval": "day",
                "shown_as": "Lifecycle",
                "smoothing_intervals": "1",
                "entity_id": "$pageview",
                "entity_type": "events",
                "entity_math": "total",
                "target_date": "2020-01-13",
                "entity_order": "0",
                "lifecycle_type": "dormant",
            },
            self.team.pk,
        )
        self.assertEqual(_insert_cohort_from_insight_filter.call_count, 2)

        insert_cohort_from_insight_filter(
            cohort_id,
            {
                "date_from": "2020-01-12T00:00:00Z",
                "date_to": "2020-01-19T00:00:00Z",
                "events": [{"id": "$pageview", "type": "events", "order": 0}],
                "insight": "LIFECYCLE",
                "interval": "day",
                "shown_as": "Lifecycle",
                "smoothing_intervals": "1",
                "entity_id": "$pageview",
                "entity_type": "events",
                "entity_math": "total",
                "target_date": "2020-01-13",
                "entity_order": "0",
                "lifecycle_type": "dormant",
            },
        )

        cohort = Cohort.objects.get(pk=response["id"])
        self.assertEqual(cohort.count, 2)
        people_result = Person.objects.filter(cohort__id=cohort.pk).values_list("id", flat=True)
        self.assertCountEqual([people[1].id, people[2].id], people_result)
