from unittest.mock import patch
from uuid import uuid4

from freezegun import freeze_time

from ee.clickhouse.models.event import create_event
from posthog.models.cohort import Cohort
from posthog.models.person import Person
from posthog.tasks.calculate_cohort import insert_cohort_from_query
from posthog.tasks.test.test_calculate_cohort import calculate_cohort_test_factory


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid)


class TestClickhouseCalculateCohort(calculate_cohort_test_factory(_create_event, _create_person)):  # type: ignore
    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_query.delay")
    def test_create_stickiness_cohort(self, _insert_cohort_from_query):
        _create_person(team_id=self.team.pk, distinct_ids=["blabla"])
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="blabla",
            properties={"$math_prop": 1},
            timestamp="2021-01-01T12:00:00Z",
        )
        response = self.client.post(
            "/api/cohort/?insight=STICKINESS&properties=%5B%5D&interval=day&display=ActionsLineGraph&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%5D&shown_as=Stickiness&date_from=2021-01-01&entity_id=%24pageview&entity_type=events&stickiness_days=1&label=%24pageview",
            {"name": "test", "is_static": True},
        ).json()

        cohort_id = response["id"]

        _insert_cohort_from_query.assert_called_once_with(
            cohort_id,
            "STICKINESS",
            {
                "date_from": "2021-01-01",
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "math": None,
                        "math_property": None,
                        "properties": [],
                    }
                ],
                "insight": "STICKINESS",
                "interval": "day",
                "selected_interval": 1,
                "shown_as": "Stickiness",
            },
            entity_data={
                "id": "$pageview",
                "type": "events",
                "order": None,
                "name": "$pageview",
                "math": None,
                "math_property": None,
                "properties": [],
            },
        )
        insert_cohort_from_query(
            cohort_id,
            "STICKINESS",
            {
                "date_from": "2021-01-01",
                "events": [
                    {
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "math": None,
                        "math_property": None,
                        "properties": [],
                    }
                ],
                "insight": "STICKINESS",
                "interval": "day",
                "selected_interval": 1,
                "shown_as": "Stickiness",
            },
            entity_data={
                "id": "$pageview",
                "type": "events",
                "order": None,
                "name": "$pageview",
                "math": None,
                "math_property": None,
                "properties": [],
            },
        )
        cohort = Cohort.objects.get(pk=cohort_id)
        people = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(len(people), 1)

    @patch("posthog.tasks.calculate_cohort.insert_cohort_from_query.delay")
    def test_create_trends_cohort(self, _insert_cohort_from_query):
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
            "/api/cohort/?interval=day&display=ActionsLineGraph&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%5D&properties=%5B%5D&entity_id=%24pageview&entity_type=events&date_from=2021-01-01&date_to=2021-01-01&label=%24pageview",
            {"name": "test", "is_static": True},
        ).json()
        cohort_id = response["id"]
        _insert_cohort_from_query.assert_called_once_with(
            cohort_id,
            "TRENDS",
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
                        "properties": [],
                    }
                ],
                "entity_id": "$pageview",
                "entity_type": "events",
                "insight": "TRENDS",
                "interval": "day",
            },
            entity_data={
                "id": "$pageview",
                "type": "events",
                "order": None,
                "name": "$pageview",
                "math": None,
                "math_property": None,
                "properties": [],
            },
        )
        insert_cohort_from_query(
            cohort_id,
            "TRENDS",
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
                        "properties": [],
                    }
                ],
                "entity_id": "$pageview",
                "entity_type": "events",
                "insight": "TRENDS",
                "interval": "day",
            },
            entity_data={
                "id": "$pageview",
                "type": "events",
                "order": 0,
                "name": "$pageview",
                "math": None,
                "math_property": None,
                "properties": [],
            },
        )
        cohort = Cohort.objects.get(pk=cohort_id)
        people = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(len(people), 1)
