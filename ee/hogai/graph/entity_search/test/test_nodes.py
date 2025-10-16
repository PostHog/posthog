import pytest
from unittest.mock import AsyncMock, Mock, patch

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from ee.hogai.graph.entity_search.nodes import EntitySearchNode
from ee.hogai.utils.types.base import AssistantState


class TestEntitySearchNode:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.team = Mock()
        self.team.id = 123
        self.team.project_id = 456
        self.team.organization = Mock()
        self.team.organization.id = 789
        self.user = Mock()
        self.node = EntitySearchNode(self.team, self.user)

    @parameterized.expand(
        [
            ("insight", "test_insight_id", "/project/{team_id}/insights/test_insight_id"),
            ("dashboard", "test_dashboard_id", "/project/{team_id}/dashboard/test_dashboard_id"),
            ("experiment", "test_experiment_id", "/project/{team_id}/experiments/test_experiment_id"),
            ("feature_flag", "test_flag_id", "/project/{team_id}/feature_flags/test_flag_id"),
            ("notebook", "test_notebook_id", "/project/{team_id}/notebooks/test_notebook_id"),
            ("action", "test_action_id", "/project/{team_id}/data-management/actions/test_action_id"),
            ("cohort", "test_cohort_id", "/project/{team_id}/cohorts/test_cohort_id"),
            ("event_definition", "test_event_id", "/project/{team_id}/data-management/events/test_event_id"),
            ("survey", "test_survey_id", "/project/{team_id}/surveys/test_survey_id"),
            ("unknown_type", "test_id", "/project/{team_id}/unknown_type/test_id"),
        ]
    )
    def test_build_url(self, entity_type, result_id, expected_path):
        url = self.node.build_url(entity_type, result_id)
        expected_url = expected_path.format(team_id=self.team.id)
        assert url == expected_url

    @parameterized.expand(
        [
            (
                {
                    "type": "insight",
                    "result_id": "123",
                    "extra_fields": {"name": "Test Insight", "key": "test_key", "description": "Test description"},
                },
                ["**[Test Insight]", " - Key: test_key", " - Description: Test description"],
            ),
            (
                {"type": "dashboard", "result_id": "456", "extra_fields": {"name": "Test Dashboard"}},
                ["**[Test Dashboard]"],
            ),
            (
                {"type": "cohort", "result_id": "789", "extra_fields": {}},
                ["**[COHORT 789]"],
            ),
            (
                {
                    "type": "action",
                    "result_id": "101",
                    "extra_fields": {"name": "Click Event", "description": "Tracks clicks"},
                },
                ["**[Click Event]", " - Description: Tracks clicks"],
            ),
        ]
    )
    def test_get_formatted_entity_result(self, result, expected_parts):
        formatted = self.node._get_formatted_entity_result(result)
        formatted_str = "".join(formatted)

        for expected_part in expected_parts:
            assert expected_part in formatted_str

    def test_format_results_for_display_no_results(self):
        content = self.node._format_results_for_display(
            query="test query", entity_types=["insight", "dashboard"], results=[], counts={}
        )

        assert "No entities found" in content
        assert "test query" in content
        assert "['insight', 'dashboard']" in content

    def test_format_results_for_display_with_results(self):
        results = [
            {"type": "insight", "result_id": "123", "extra_fields": {"name": "Test Insight"}},
            {"type": "dashboard", "result_id": "456", "extra_fields": {"name": "Test Dashboard"}},
        ]
        counts = {"insight": 1, "dashboard": 1}

        content = self.node._format_results_for_display(
            query="test query", entity_types=["insight", "dashboard"], results=results, counts=counts
        )

        assert "Successfully found 2 entities" in content
        assert "Test Insight" in content
        assert "Test Dashboard" in content
        assert "Insight: 1" in content
        assert "Dashboard: 1" in content
        assert "VERY IMPORTANT INSTRUCTIONS" in content

    @pytest.mark.asyncio
    async def test_arun_no_query(self):
        state = AssistantState(entity_search_query=None, root_tool_call_id="test_call_id")
        config = RunnableConfig()

        result = await self.node.arun(state, config)

        assert len(result.messages) == 1
        assert "No search query" in result.messages[0].content
        assert result.entity_search_query is None
        assert result.root_tool_call_id is None

    @pytest.mark.asyncio
    @patch("ee.hogai.graph.entity_search.nodes.class_queryset")
    @patch("ee.hogai.graph.entity_search.nodes.database_sync_to_async")
    async def test_arun_with_results(self, mock_db_sync, mock_class_queryset):
        all_results = [
            {"type": "insight", "result_id": "123", "extra_fields": {"name": "Test Insight"}, "rank": 0.95},
            {"type": "dashboard", "result_id": "456", "extra_fields": {"name": "Test Dashboard"}, "rank": 0.90},
            {"type": "notebook", "result_id": "789", "extra_fields": {"name": "Test Notebook"}, "rank": 0.85},
            {"type": "action", "result_id": "101", "extra_fields": {"name": "Test Action"}, "rank": 0.80},
        ]

        call_count = 0
        entity_types_order = ["insight", "dashboard", "notebook", "action"]

        def side_effect_func(**kwargs):
            nonlocal call_count
            entity_type = entity_types_order[call_count]
            call_count += 1

            qs = Mock()
            type_results = [r for r in all_results if r["type"] == entity_type]
            qs.__getitem__ = Mock(return_value=type_results)
            return (qs, None)

        def async_wrapper(func):
            async def inner(*args, **kwargs):
                return func(*args, **kwargs)

            return inner

        mock_db_sync.side_effect = async_wrapper
        mock_class_queryset.side_effect = side_effect_func

        state = AssistantState(
            entity_search_query="test query",
            entity_search_types=["insight", "dashboard", "notebook", "action"],
            root_tool_call_id="test_call_id",
        )
        config = RunnableConfig()

        result = await self.node.arun(state, config)

        assert len(result.messages) == 1
        assert "Test Insight" in result.messages[0].content
        assert "Test Dashboard" in result.messages[0].content
        assert "Test Notebook" in result.messages[0].content
        assert "Test Action" in result.messages[0].content

        for mock_result in all_results:
            assert self.node.build_url(mock_result["type"], mock_result["result_id"]) in result.messages[0].content
        assert result.entity_search_query is None
        assert result.root_tool_call_id is None

    @pytest.mark.asyncio
    @patch("ee.hogai.graph.entity_search.nodes.class_queryset")
    @patch("ee.hogai.graph.entity_search.nodes.database_sync_to_async")
    @patch("ee.hogai.graph.entity_search.nodes.capture_exception")
    async def test_arun_exception_handling(self, mock_capture, mock_db_sync, mock_class_queryset):
        mock_db_sync.side_effect = Exception("Database error")

        state = AssistantState(entity_search_query="test query", root_tool_call_id="test_call_id")
        config = RunnableConfig()

        result = await self.node.arun(state, config)

        assert len(result.messages) == 1
        assert "Error searching entities" in result.messages[0].content
        mock_capture.assert_called_once()

    def test_router(self):
        state = AssistantState()
        result = self.node.router(state)
        assert result == "root"

    @pytest.mark.asyncio
    async def test_gather_bounded_limits_concurrency(self):
        call_count = 0
        max_concurrent = 0
        current_concurrent = 0

        async def mock_coro():
            nonlocal call_count, max_concurrent, current_concurrent
            call_count += 1
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
            await AsyncMock()()
            current_concurrent -= 1
            return "result"

        coros = [mock_coro() for _ in range(20)]
        results = await self.node._gather_bounded(5, coros)

        assert len(results) == 20
        assert max_concurrent <= 5
