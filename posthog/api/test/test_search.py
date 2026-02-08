import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import Mock

from django.db import connection

from posthog.api.search import ENTITY_MAP, class_queryset, search_entities
from posthog.helpers.full_text_search import process_query
from posthog.models import Dashboard, FeatureFlag, Insight, Team
from posthog.models.event_definition import EventDefinition
from posthog.models.hog_flow.hog_flow import HogFlow

from products.early_access_features.backend.models import EarlyAccessFeature
from products.notebooks.backend.models import Notebook


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

    def test_early_access_features(self):
        EarlyAccessFeature.objects.create(name="first feature", team=self.team, stage="beta")
        EarlyAccessFeature.objects.create(name="second feature", team=self.team, stage="beta")
        EarlyAccessFeature.objects.create(name="third feature", team=self.team, stage="alpha")

        response = self.client.get("/api/projects/@current/search?q=sec&entities=early_access_feature")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["counts"]["early_access_feature"], 1)

        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "early_access_feature")
        self.assertEqual(results[0]["extra_fields"]["name"], "second feature")

    def test_hog_flows(self):
        HogFlow.objects.create(name="first workflow", team=self.team)
        HogFlow.objects.create(name="second workflow", team=self.team)
        HogFlow.objects.create(name="third workflow", team=self.team)

        response = self.client.get("/api/projects/@current/search?q=sec&entities=hog_flow")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["counts"]["hog_flow"], 1)

        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type"], "hog_flow")
        self.assertEqual(results[0]["extra_fields"]["name"], "second workflow")

    def test_filters(self):
        # Create feature flags with specific tags to identify them
        FeatureFlag.objects.create(
            name="filter test active one", key="filter_active1", team=self.team, created_by=self.user, active=True
        )
        FeatureFlag.objects.create(
            name="filter test active two", key="filter_active2", team=self.team, created_by=self.user, active=True
        )
        FeatureFlag.objects.create(
            name="filter test inactive", key="filter_inactive1", team=self.team, created_by=self.user, active=False
        )

        # Mock view with user_access_control
        mock_view = Mock()
        mock_view.user_access_control.filter_queryset_by_access_level = lambda qs: qs

        # Test without filters - should get all flags for this team
        qs_no_filter, entity_name = class_queryset(
            view=mock_view,
            klass=FeatureFlag,
            project_id=self.team.project_id,
            query=None,
            search_fields={"key": "A", "name": "C"},
            extra_fields=["key", "name", "active"],
            filters=None,
        )
        count_without_filter = qs_no_filter.count()

        # Test with filters - should get fewer results (only active ones)
        qs_with_filter, entity_name = class_queryset(
            view=mock_view,
            klass=FeatureFlag,
            project_id=self.team.project_id,
            query=None,
            search_fields={"key": "A", "name": "C"},
            extra_fields=["key", "name", "active"],
            filters={"active": True},
        )
        count_with_filter = qs_with_filter.count()

        # The filtered count should be less than unfiltered (we created 1 inactive flag)
        self.assertLess(count_with_filter, count_without_filter)

        # Verify all returned flags with filter are active
        results = list(qs_with_filter)
        for result in results:
            self.assertTrue(result["extra_fields"]["active"])

        # Test with specific key filter
        qs_key_filter, entity_name = class_queryset(
            view=mock_view,
            klass=FeatureFlag,
            project_id=self.team.project_id,
            query=None,
            search_fields={"key": "A", "name": "C"},
            extra_fields=["key", "name"],
            filters={"key": "filter_active1"},
        )
        self.assertEqual(qs_key_filter.count(), 1)
        self.assertEqual(next(iter(qs_key_filter))["extra_fields"]["key"], "filter_active1")

    def test_search_entities_returns_total_count(self):
        for i in range(5):
            Insight.objects.create(team=self.team, name=f"total count insight {i}", saved=True)

        mock_view = Mock()
        mock_view.user_access_control.filter_queryset_by_access_level = lambda qs: qs

        results, counts, total_count = search_entities(
            entities={"insight"},
            query="total count",
            project_id=self.team.project_id,
            view=mock_view,
            entity_map=ENTITY_MAP,
        )

        self.assertEqual(total_count, 5)
        self.assertEqual(len(results), 5)

    def test_search_entities_pagination_with_limit(self):
        for i in range(10):
            Insight.objects.create(team=self.team, name=f"pagination limit {i}", saved=True)

        mock_view = Mock()
        mock_view.user_access_control.filter_queryset_by_access_level = lambda qs: qs

        results, counts, total_count = search_entities(
            entities={"insight"},
            query="pagination limit",
            project_id=self.team.project_id,
            view=mock_view,
            entity_map=ENTITY_MAP,
            limit=3,
        )

        self.assertEqual(total_count, 10)
        self.assertEqual(len(results), 3)

    def test_search_entities_pagination_with_offset(self):
        for i in range(10):
            Insight.objects.create(team=self.team, name=f"pagination offset {i}", saved=True)

        mock_view = Mock()
        mock_view.user_access_control.filter_queryset_by_access_level = lambda qs: qs

        results_page1, _, total_count1 = search_entities(
            entities={"insight"},
            query="pagination offset",
            project_id=self.team.project_id,
            view=mock_view,
            entity_map=ENTITY_MAP,
            limit=3,
            offset=0,
        )
        results_page2, _, total_count2 = search_entities(
            entities={"insight"},
            query="pagination offset",
            project_id=self.team.project_id,
            view=mock_view,
            entity_map=ENTITY_MAP,
            limit=3,
            offset=3,
        )

        self.assertEqual(total_count1, 10)
        self.assertEqual(total_count2, 10)
        self.assertEqual(len(results_page1), 3)
        self.assertEqual(len(results_page2), 3)

        page1_ids = {r["result_id"] for r in results_page1}
        page2_ids = {r["result_id"] for r in results_page2}
        self.assertEqual(len(page1_ids & page2_ids), 0)


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
