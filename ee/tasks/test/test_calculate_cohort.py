import json
import urllib.parse
from unittest.mock import patch

from freezegun import freeze_time

from ee.clickhouse.util import ClickhouseTestMixin
from posthog.client import sync_execute
from posthog.models.cohort import Cohort
from posthog.models.person import Person
from posthog.tasks.calculate_cohort import insert_cohort_from_insight_filter
from posthog.tasks.test.test_calculate_cohort import calculate_cohort_test_factory
from posthog.test.base import _create_event, _create_person


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
                [{"key": "$domain", "value": "app.posthog.com", "operator": "icontains", "type": "event"}]
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
                        "math_property": None,
                        "math_group_type_index": None,
                        "properties": [],
                    }
                ],
                "properties": [
                    {"key": "$domain", "value": "app.posthog.com", "operator": "icontains", "type": "event"}
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
                        "math_property": None,
                    },
                    {
                        "id": "$another_view",
                        "math": None,
                        "name": "$another_view",
                        "type": "events",
                        "order": 1,
                        "properties": [],
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
                "events": '[{"id": "$pageview", "math": null, "name": "$pageview", "type": "events", "order": 0, "properties": [], "math_property": null}, {"id": "$another_view", "math": null, "name": "$another_view", "type": "events", "order": 1, "properties": [], "math_property": null}]',
                "display": "FunnelViz",
                "interval": "day",
                "layout": "horizontal",
                "date_from": "2021-01-01",
                "date_to": "2021-01-07",
                "funnel_step": "1",
            },
        )

        insert_cohort_from_insight_filter(
            cohort_id, params,
        )

        cohort = Cohort.objects.get(pk=cohort_id)
        people = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(cohort.errors_calculating, 0)
        self.assertEqual(people.count(), 1)
