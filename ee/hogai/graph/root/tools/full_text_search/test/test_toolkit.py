from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.conf import settings

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from ee.hogai.context import AssistantContextManager
from ee.hogai.graph.root.tools.full_text_search.tool import ENTITY_MAP, EntitySearchTool, FTSKind
from ee.hogai.graph.shared_prompts import HYPERLINK_USAGE_INSTRUCTIONS
from ee.hogai.utils.types.base import AssistantState


class TestEntitySearchToolkit(BaseTest):
    def setUp(self):
        super().setUp()
        self.team = Mock()
        self.team.id = 123
        self.team.project_id = 456
        self.team.organization = Mock()
        self.team.organization.id = 789
        self.user = Mock()
        self.toolkit = EntitySearchTool(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
            config=RunnableConfig(configurable={}),
            context_manager=AssistantContextManager(self.team, self.user, {}),
        )

    @parameterized.expand(
        [
            ("dashboard", "test_dashboard_id", "/project/{team_id}/dashboard/test_dashboard_id"),
            ("experiment", "test_experiment_id", "/project/{team_id}/experiments/test_experiment_id"),
            ("feature_flag", "test_flag_id", "/project/{team_id}/feature_flags/test_flag_id"),
            ("action", "test_action_id", "/project/{team_id}/data-management/actions/test_action_id"),
            ("cohort", "test_cohort_id", "/project/{team_id}/cohorts/test_cohort_id"),
            ("survey", "test_survey_id", "/project/{team_id}/surveys/test_survey_id"),
        ]
    )
    def test_build_url(self, entity_type, result_id, expected_path):
        url = self.toolkit._build_url(entity_type, result_id)
        expected_url = f"{settings.SITE_URL}{expected_path.format(team_id=self.team.id)}"
        assert url == expected_url

    @parameterized.expand(
        [
            (
                {"type": "dashboard", "result_id": "456", "extra_fields": {"name": "Test Dashboard"}},
                ["name: Test Dashboard"],
            ),
            (
                {"type": "cohort", "result_id": "789", "extra_fields": {"filters": "test_filters"}},
                ["name: COHORT 789", "filters: test_filters"],
            ),
            (
                {
                    "type": "action",
                    "result_id": "101",
                    "extra_fields": {"name": "Click Event", "description": "Tracks clicks"},
                },
                ["name: Click Event", "description: Tracks clicks"],
            ),
        ]
    )
    def test_get_formatted_entity_result(self, result, expected_parts):
        formatted = self.toolkit._get_formatted_entity_result(result)
        formatted_str = "".join(formatted)
        for expected_part in expected_parts:
            assert expected_part in formatted_str

    def test_format_results_for_display_no_results(self):
        content = self.toolkit._format_results_for_display(
            query="test query", entity_types={"cohort", "dashboard"}, results=[], counts={}
        )

        assert "No entities found" in content
        assert "test query" in content
        assert "dashboard" in content
        assert "cohort" in content

    def test_format_results_for_display_with_results(self):
        results = [
            {"type": "cohort", "result_id": "123", "extra_fields": {"name": "Test cohort"}},
            {"type": "dashboard", "result_id": "456", "extra_fields": {"name": "Test Dashboard"}},
        ]
        counts: dict[str, int | None] = {"cohort": 1, "dashboard": 1}

        content = self.toolkit._format_results_for_display(
            query="test query", entity_types={"cohort", "dashboard"}, results=results, counts=counts
        )

        assert "Successfully found 2 entities" in content
        assert "Test cohort" in content
        assert "Test Dashboard" in content
        assert "Cohort: 1" in content
        assert "Dashboard: 1" in content
        assert HYPERLINK_USAGE_INSTRUCTIONS in content

    async def test_arun_no_query(self):
        result = await self.toolkit.execute(query=None, search_kind=FTSKind.COHORTS)  # type: ignore

        assert "No search query was provided" in result

    @patch("ee.hogai.graph.root.tools.full_text_search.tool.search_entities")
    @patch("ee.hogai.graph.root.tools.full_text_search.tool.database_sync_to_async")
    async def test_search_no_entity_types(self, mock_db_sync, mock_search_entities):
        all_results: list[dict] = [
            {"type": "cohort", "result_id": "123", "extra_fields": {"name": "Test cohort"}, "rank": 0.95},
            {"type": "dashboard", "result_id": "456", "extra_fields": {"name": "Test Dashboard"}, "rank": 0.90},
            {"type": "action", "result_id": "101", "extra_fields": {"name": "Test Action"}, "rank": 0.80},
        ]

        def side_effect_func(entities, query, project_id, view, entity_map):
            return (all_results, {entity: 1 for entity in entities})

        def async_wrapper(func):
            async def inner(*args, **kwargs):
                return func(*args, **kwargs)

            return inner

        mock_db_sync.side_effect = async_wrapper
        mock_search_entities.side_effect = side_effect_func

        _ = await self.toolkit.execute(query="test query", search_kind=FTSKind.ALL)

        mock_search_entities.assert_called_once_with(
            set(ENTITY_MAP.keys()), "test query", self.team.project_id, self.toolkit, ENTITY_MAP
        )

    @patch("ee.hogai.graph.root.tools.full_text_search.tool.search_entities")
    @patch("ee.hogai.graph.root.tools.full_text_search.tool.database_sync_to_async")
    async def test_arun_with_results(self, mock_db_sync, mock_search_entities):
        all_results: list[dict] = [
            {
                "kind": FTSKind.COHORTS,
                "type": "cohort",
                "result_id": "123",
                "extra_fields": {"name": "Test cohort"},
                "rank": 0.95,
            },
            {
                "kind": FTSKind.DASHBOARDS,
                "type": "dashboard",
                "result_id": "456",
                "extra_fields": {"name": "Test Dashboard"},
                "rank": 0.90,
            },
            {
                "kind": FTSKind.ACTIONS,
                "type": "action",
                "result_id": "101",
                "extra_fields": {"name": "Test Action"},
                "rank": 0.80,
            },
        ]

        def side_effect_func(entities, query, project_id, view, entity_map):
            result = [result for result in all_results if result["type"] in entities]
            return (result, {result["type"]: len(result) for result in result})

        def async_wrapper(func):
            async def inner(*args, **kwargs):
                return func(*args, **kwargs)

            return inner

        mock_db_sync.side_effect = async_wrapper
        mock_search_entities.side_effect = side_effect_func

        for expected_result in all_results:
            result = await self.toolkit.execute(query="test query", search_kind=expected_result["kind"])
            assert expected_result["type"] in result
            assert expected_result["extra_fields"]["name"] in result
            assert self.toolkit._build_url(expected_result["type"], expected_result["result_id"]) in result
            assert HYPERLINK_USAGE_INSTRUCTIONS in result

    @patch("ee.hogai.graph.root.tools.full_text_search.tool.database_sync_to_async")
    @patch("ee.hogai.graph.root.tools.full_text_search.tool.capture_exception")
    async def test_arun_exception_handling(self, mock_capture, mock_db_sync):
        mock_db_sync.side_effect = Exception("Database error")

        result = await self.toolkit.execute(query="test query", search_kind=FTSKind.DASHBOARDS)

        assert "Database error" in result

    async def test_search_entities_invalid_entity_type(self):
        result = await self.toolkit.execute(query="test query", search_kind="invalid_type")  # type: ignore

        assert "Invalid entity kind: invalid_type. Will not perform search for it." in result
