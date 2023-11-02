import pytest

from django.db import connection

from posthog.api.search import process_query
from posthog.test.base import APIBaseTest

from posthog.models import Dashboard, FeatureFlag, Team


class TestSearch(APIBaseTest):
    def setUp(self):
        super().setUp()

        Dashboard.objects.create(team=self.team, created_by=self.user)
        Dashboard.objects.create(name="second dashboard", team=self.team, created_by=self.user)
        Dashboard.objects.create(name="third dashboard", team=self.team, created_by=self.user)

        FeatureFlag.objects.create(key="a", team=self.team, created_by=self.user)
        FeatureFlag.objects.create(name="second feature flag", key="b", team=self.team, created_by=self.user)
        FeatureFlag.objects.create(name="third feature flag", key="c", team=self.team, created_by=self.user)

    def test_search(self):
        response = self.client.get("/api/projects/@current/search?q=sec")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 2)
        self.assertEqual(response.json()["counts"]["action"], 0)
        self.assertEqual(response.json()["counts"]["dashboard"], 1)
        self.assertEqual(response.json()["counts"]["feature_flag"], 1)

    def test_search_without_query(self):
        response = self.client.get("/api/projects/@current/search")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 6)
        self.assertEqual(response.json()["counts"]["action"], 0)
        self.assertEqual(response.json()["counts"]["dashboard"], 3)
        self.assertEqual(response.json()["counts"]["feature_flag"], 3)

    def test_search_with_fully_invalid_query(self):
        response = self.client.get("/api/projects/@current/search?q=%3E")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 6)
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
