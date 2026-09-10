from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.db import DEFAULT_DB_ALIAS, connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.models import EventDefinition, PropertyDefinition
from posthog.taxonomy import definition_search
from posthog.taxonomy.definition_search import is_large_project


class TestIsLargeProject(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        for name in ("a", "b", "c"):
            EventDefinition.objects.create(team=self.team, name=name)

    @parameterized.expand(
        [
            ("small_project", 3, False),
            ("large_project", 2, True),
        ]
    )
    def test_follows_the_definition_count(self, _name: str, max_definitions: int, expected: bool) -> None:
        with patch.object(definition_search, "PROJECT_SCAN_MAX_DEFINITIONS", max_definitions):
            assert is_large_project("posthog_eventdefinition", self.team.pk, DEFAULT_DB_ALIAS) is expected

    def test_is_cached_per_table_and_project(self) -> None:
        is_large_project("posthog_eventdefinition", self.team.pk, DEFAULT_DB_ALIAS)

        with self.assertNumQueries(0):
            assert is_large_project("posthog_eventdefinition", self.team.pk, DEFAULT_DB_ALIAS) is False
        with self.assertNumQueries(1):
            is_large_project("posthog_propertydefinition", self.team.pk, DEFAULT_DB_ALIAS)
        with self.assertNumQueries(1):
            is_large_project("posthog_eventdefinition", self.team.pk + 1, DEFAULT_DB_ALIAS)

    def test_reads_a_plan_name_cached_by_an_earlier_release(self) -> None:
        cache.set(f"taxonomy_search_plan:posthog_eventdefinition:{self.team.pk}", "trigram")

        with self.assertNumQueries(0):
            assert is_large_project("posthog_eventdefinition", self.team.pk, DEFAULT_DB_ALIAS) is True

    @parameterized.expand([("cache_read_fails", "get"), ("cache_write_fails", "set")])
    def test_survives_a_cache_outage(self, _name: str, failing_method: str) -> None:
        with patch.object(cache, failing_method, side_effect=ConnectionError("redis down")):
            assert is_large_project("posthog_eventdefinition", self.team.pk, DEFAULT_DB_ALIAS) is False


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
