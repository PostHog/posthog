from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.db import DEFAULT_DB_ALIAS, connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.models import EventDefinition, PropertyDefinition
from posthog.taxonomy import definition_search
from posthog.taxonomy.definition_search import search_plan


class TestSearchPlan(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        for name in ("a", "b", "c"):
            EventDefinition.objects.create(team=self.team, name=name)

    @parameterized.expand(
        [
            ("small_project_scans_its_own_rows", 3, "project_scan"),
            ("huge_project_keeps_the_trigram_index", 2, "trigram"),
        ]
    )
    def test_plan_follows_the_definition_count(self, _name: str, max_definitions: int, expected: str) -> None:
        with patch.object(definition_search, "PROJECT_SCAN_MAX_DEFINITIONS", max_definitions):
            assert search_plan("posthog_eventdefinition", self.team.pk, DEFAULT_DB_ALIAS) == expected

    def test_plan_is_cached_per_table_and_project(self) -> None:
        search_plan("posthog_eventdefinition", self.team.pk, DEFAULT_DB_ALIAS)

        with self.assertNumQueries(0):
            assert search_plan("posthog_eventdefinition", self.team.pk, DEFAULT_DB_ALIAS) == "project_scan"
        with self.assertNumQueries(1):
            search_plan("posthog_propertydefinition", self.team.pk, DEFAULT_DB_ALIAS)
        with self.assertNumQueries(1):
            search_plan("posthog_eventdefinition", self.team.pk + 1, DEFAULT_DB_ALIAS)

    @parameterized.expand([("cache_read_fails", "get"), ("cache_write_fails", "set")])
    def test_plan_survives_a_cache_outage(self, _name: str, failing_method: str) -> None:
        with patch.object(cache, failing_method, side_effect=ConnectionError("redis down")):
            assert search_plan("posthog_eventdefinition", self.team.pk, DEFAULT_DB_ALIAS) == "project_scan"


class TestDefinitionEndpointsUseSearchPlan(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        EventDefinition.objects.create(team=self.team, name="foo")
        PropertyDefinition.objects.create(team=self.team, name="foo")

    @parameterized.expand(
        [
            ("event_definitions_small_project", "event_definitions", 1, "lower(name) like lower("),
            ("event_definitions_huge_project", "event_definitions", 0, "name ilike "),
            ("property_definitions_small_project", "property_definitions", 1, "lower(name) like lower("),
            ("property_definitions_huge_project", "property_definitions", 0, "name ilike "),
        ]
    )
    def test_search_predicate_follows_the_plan(
        self, _name: str, endpoint: str, max_definitions: int, expected_predicate: str
    ) -> None:
        with (
            patch.object(definition_search, "PROJECT_SCAN_MAX_DEFINITIONS", max_definitions),
            CaptureQueriesContext(connection) as queries,
        ):
            response = self.client.get(f"/api/projects/{self.team.pk}/{endpoint}/?search=foo")

        assert response.status_code == 200
        search_queries = [q["sql"] for q in queries.captured_queries if "%foo%" in q["sql"]]
        assert search_queries, "no search query was captured"
        assert all(expected_predicate in sql for sql in search_queries), search_queries
