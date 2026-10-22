from collections.abc import Callable

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.db import DEFAULT_DB_ALIAS, connection
from django.test.utils import CaptureQueriesContext

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from parameterized import parameterized

from posthog.models import EventDefinition, PropertyDefinition
from posthog.taxonomy import definition_search
from posthog.taxonomy.definition_search import project_definition_scale, search_plan

TEAM_SCAN_SEARCH = "name IN (SELECT name FROM posthog_eventdefinition WHERE team_id = "


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
        with (
            patch.object(definition_search, "PROJECT_SCAN_MAX_DEFINITIONS", max_definitions),
            patch.object(definition_search, "EVENT_SEARCH_TEAM_SCAN_MAX_DEFINITIONS", max_definitions),
        ):
            assert search_plan("posthog_eventdefinition", self.team.pk, DEFAULT_DB_ALIAS) == expected
            scale = project_definition_scale("posthog_eventdefinition", self.team.pk, DEFAULT_DB_ALIAS)
            assert scale.large is (expected == "trigram")
            assert scale.searches_by_trigram is (expected == "trigram")

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

    @parameterized.expand(
        [
            (
                "property_search_keeps_the_unordered_count",
                search_plan,
                "posthog_propertydefinition",
                False,
                "COALESCE(project_id, team_id) =",
                50_001,
            ),
            (
                "event_list_counts_past_the_team_scan_threshold_on_the_team_index",
                project_definition_scale,
                "posthog_eventdefinition",
                True,
                "WHERE team_id =",
                2_000_001,
            ),
        ]
    )
    def test_size_check_statement_per_reader(
        self, _name: str, check: Callable[..., object], table: str, ordered: bool, scope: str, limit: int
    ) -> None:
        with CaptureQueriesContext(connection) as queries:
            check(table, self.team.pk, DEFAULT_DB_ALIAS)

        (size_check,) = [q["sql"] for q in queries.captured_queries if "bounded" in q["sql"]]
        assert f"FROM {table} " in size_check
        assert scope in size_check
        assert ("ORDER BY name" in size_check) is ordered
        assert f"LIMIT {limit}" in size_check

    @parameterized.expand([("search_plan", search_plan), ("project_definition_scale", project_definition_scale)])
    def test_plan_is_recorded_on_the_request_span(self, _name: str, read_plan: Callable[..., object]) -> None:
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        with provider.get_tracer(__name__).start_as_current_span("definitions_list"):
            read_plan("posthog_eventdefinition", self.team.pk, DEFAULT_DB_ALIAS)

        attributes = exporter.get_finished_spans()[0].attributes or {}
        assert attributes["taxonomy_search_plan"] == "project_scan"


class TestDefinitionEndpointsUseSearchPlan(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        EventDefinition.objects.create(team=self.team, name="foo")
        PropertyDefinition.objects.create(team=self.team, name="foo")

    @parameterized.expand(
        [
            ("event_definitions_small_project", "event_definitions", 1, 1, TEAM_SCAN_SEARCH),
            ("event_definitions_large_project_below_team_scan_limit", "event_definitions", 0, 1, TEAM_SCAN_SEARCH),
            ("event_definitions_huge_project", "event_definitions", 0, 0, "name ilike "),
            ("property_definitions_small_project", "property_definitions", 1, 1, "lower(name) like lower("),
            ("property_definitions_huge_project", "property_definitions", 0, 1, "name ilike "),
        ]
    )
    def test_search_predicate_follows_the_plan(
        self,
        _name: str,
        endpoint: str,
        project_scan_max: int,
        event_team_scan_max: int,
        expected_predicate: str,
    ) -> None:
        with (
            patch.object(definition_search, "PROJECT_SCAN_MAX_DEFINITIONS", project_scan_max),
            patch.object(definition_search, "EVENT_SEARCH_TEAM_SCAN_MAX_DEFINITIONS", event_team_scan_max),
            CaptureQueriesContext(connection) as queries,
        ):
            response = self.client.get(f"/api/projects/{self.team.pk}/{endpoint}/?search=foo")

        assert response.status_code == 200
        assert [r["name"] for r in response.json()["results"]] == ["foo"]
        search_queries = [q["sql"] for q in queries.captured_queries if "%foo%" in q["sql"]]
        assert search_queries, "no search query was captured"
        assert all(expected_predicate in sql for sql in search_queries), search_queries
