import pytest
from posthog.test.base import APIBaseTest

from django.db import connection

from posthog.helpers.full_text_search import process_query
from posthog.models import Dashboard, FeatureFlag, Insight, Notebook, Team
from posthog.models.event_definition import EventDefinition


class TestSearch(APIBaseTest):
    insight_1: Insight
    dashboard_1: Dashboard

    def setUp(self):
        super().setUp()

        Insight.objects.create(team=self.team, derived_name="derived name")
        self.insight_1 = Insight.objects.create(team=self.team, name="second insight")
        Insight.objects.create(team=self.team, name="third insight")

        Dashboard.objects.create(team=self.team, created_by=self.user)
        self.dashboard_1 = Dashboard.objects.create(name="second dashboard", team=self.team, created_by=self.user)
        Dashboard.objects.create(name="third dashboard", team=self.team, created_by=self.user)

        FeatureFlag.objects.create(key="a", team=self.team, created_by=self.user)
        FeatureFlag.objects.create(name="second feature flag", key="b", team=self.team, created_by=self.user)
        FeatureFlag.objects.create(name="third feature flag", key="c", team=self.team, created_by=self.user)

        Notebook.objects.create(team=self.team, created_by=self.user, short_id="01234", title="first notebook")
        self.notebook_1 = Notebook.objects.create(
            team=self.team, created_by=self.user, short_id="56789", title="second notebook"
        )

    def test_search(self):
        response = self.client.get("/api/projects/@current/search?q=sec")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 4)
        self.assertEqual(response.json()["counts"]["action"], 0)
        self.assertEqual(response.json()["counts"]["dashboard"], 1)
        self.assertEqual(response.json()["counts"]["feature_flag"], 1)
        self.assertEqual(response.json()["counts"]["insight"], 1)
        self.assertEqual(response.json()["counts"]["notebook"], 1)

    def test_search_without_query(self):
        response = self.client.get("/api/projects/@current/search")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 11)
        self.assertEqual(response.json()["counts"]["action"], 0)
        self.assertEqual(response.json()["counts"]["dashboard"], 3)
        self.assertEqual(response.json()["counts"]["feature_flag"], 3)
        self.assertEqual(response.json()["counts"]["insight"], 3)
        self.assertEqual(response.json()["counts"]["notebook"], 2)

    def test_search_filtered_by_entity(self):
        response = self.client.get(
            "/api/projects/@current/search?q=sec&entities=insight&entities=dashboard&entities=notebook"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 3)
        self.assertEqual(response.json()["counts"]["dashboard"], 1)
        self.assertEqual(response.json()["counts"]["insight"], 1)
        self.assertEqual(response.json()["counts"]["notebook"], 1)

    def test_response_format_and_ids(self):
        response = self.client.get(
            "/api/projects/@current/search?q=sec&entities=insight&entities=dashboard&entities=notebook"
        )

        sorted_results = sorted(response.json()["results"], key=lambda entity: entity["type"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted_results,
            [
                {
                    "rank": sorted_results[0]["rank"],
                    "type": "dashboard",
                    "result_id": str(self.dashboard_1.id),
                    "extra_fields": {"description": "", "name": "second dashboard"},
                },
                {
                    "rank": sorted_results[1]["rank"],
                    "type": "insight",
                    "result_id": self.insight_1.short_id,
                    "extra_fields": {"name": "second insight", "description": None, "query": None},
                },
                {
                    "rank": sorted_results[2]["rank"],
                    "type": "notebook",
                    "result_id": self.notebook_1.short_id,
                    "extra_fields": {"title": "second notebook", "content": None},
                },
            ],
        )

    def test_extra_fields(self):
        response = self.client.get("/api/projects/@current/search?entities=insight")

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        for result in results:
            self.assertEqual(set(result["extra_fields"].keys()), {"name", "description", "query"})

    def test_search_with_fully_invalid_query(self):
        response = self.client.get("/api/projects/@current/search?q=%3E")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 11)
        self.assertEqual(response.json()["counts"]["action"], 0)
        self.assertEqual(response.json()["counts"]["dashboard"], 3)
        self.assertEqual(response.json()["counts"]["feature_flag"], 3)

    def test_entities_from_other_teams(self):
        other_team = Team.objects.create(organization=self.organization)
        Dashboard.objects.create(name="permissions", team=self.team, created_by=self.user)
        Dashboard.objects.create(name="permissions", team=other_team, created_by=self.user)

        response = self.client.get("/api/projects/@current/search?q=permissions")

        self.assertEqual(response.json()["counts"]["dashboard"], 1)

    def test_dangerous_characters(self):
        response = self.client.get("/api/projects/@current/search?q=%21%3A%28%29%5B%5D%26%7C%3C%3E%20str1%20str2")
        self.assertEqual(response.status_code, 200)

    def test_event_definitions(self):
        EventDefinition.objects.create(name="first event", team=self.team)
        EventDefinition.objects.create(name="second event", team=self.team)
        EventDefinition.objects.create(name="third event", team=self.team)

        response = self.client.get("/api/projects/@current/search?q=sec&entities=event_definition")

        self.assertEqual(response.status_code, 200)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query,expected,dbresult",
    [
        ("som", "som:*", "'som':*"),
        ("some te", "some & te:*", "'some' & 'te':*"),
        ("we", "we:*", "'we':*"),
        ("a'&|!<>():b", "a & b:*", "'a' & 'b':*"),
        ("!", None, None),
    ],
)
def test_process_query(query, expected, dbresult):
    processed_query = process_query(query)
    assert processed_query == expected

    if dbresult is not None:
        cursor = connection.cursor()
        cursor.execute("SELECT tsquery(%s);", (processed_query,))
        result = cursor.fetchall()

        assert result[0][0] == dbresult
