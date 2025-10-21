import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized

from ee.hogai.graph.entity_search.toolkit import ENTITY_MAP, EntitySearchToolkit
from ee.hogai.graph.shared_prompts import HYPERLINK_USAGE_INSTRUCTIONS


class TestEntitySearchToolkit:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.team = Mock()
        self.team.id = 123
        self.team.project_id = 456
        self.team.organization = Mock()
        self.team.organization.id = 789
        self.user = Mock()
        self.toolkit = EntitySearchToolkit(self.team, self.user)

    @parameterized.expand(
        [
            ("insight", "test_insight_id", "/project/{team_id}/insights/test_insight_id"),
            ("dashboard", "test_dashboard_id", "/project/{team_id}/dashboard/test_dashboard_id"),
            ("experiment", "test_experiment_id", "/project/{team_id}/experiments/test_experiment_id"),
            ("feature_flag", "test_flag_id", "/project/{team_id}/feature_flags/test_flag_id"),
            ("action", "test_action_id", "/project/{team_id}/data-management/actions/test_action_id"),
            ("cohort", "test_cohort_id", "/project/{team_id}/cohorts/test_cohort_id"),
            ("survey", "test_survey_id", "/project/{team_id}/surveys/test_survey_id"),
            ("unknown_type", "test_id", "/project/{team_id}/unknown_type/test_id"),
        ]
    )
    def test_build_url(self, entity_type, result_id, expected_path):
        url = self.toolkit.build_url(entity_type, result_id)
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
                ["name: Test Insight", "key: test_key", "description: Test description"],
            ),
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
            query="test query", entity_types={"insight", "dashboard"}, results=[], counts={}
        )

        assert "No entities found" in content
        assert "test query" in content
        assert "['dashboard', 'insight']" in content

    def test_format_results_for_display_with_results(self):
        results = [
            {"type": "insight", "result_id": "123", "extra_fields": {"name": "Test Insight"}},
            {"type": "dashboard", "result_id": "456", "extra_fields": {"name": "Test Dashboard"}},
        ]
        counts: dict[str, int | None] = {"insight": 1, "dashboard": 1}

        content = self.toolkit._format_results_for_display(
            query="test query", entity_types={"insight", "dashboard"}, results=results, counts=counts
        )

        assert "Successfully found 2 entities" in content
        assert "Test Insight" in content
        assert "Test Dashboard" in content
        assert "Insight: 1" in content
        assert "Dashboard: 1" in content
        assert "VERY IMPORTANT INSTRUCTIONS" in content

    @pytest.mark.asyncio
    async def test_arun_no_query(self):
        result = await self.toolkit.search(query=None, entity_types=["insight", "dashboard", "action"])  # type: ignore

        assert "No search query was provided" in result

    @pytest.mark.asyncio
    @patch("ee.hogai.graph.entity_search.toolkit.search_entities")
    @patch("ee.hogai.graph.entity_search.toolkit.database_sync_to_async")
    async def test_search_no_entity_types(self, mock_db_sync, mock_search_entities):
        all_results = [
            {"type": "insight", "result_id": "123", "extra_fields": {"name": "Test Insight"}, "rank": 0.95},
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

        _ = await self.toolkit.search(query="test query", entity_types=[])

        mock_search_entities.assert_called_once_with(
            set(ENTITY_MAP.keys()), "test query", self.team.project_id, self.toolkit, ENTITY_MAP
        )

    @pytest.mark.asyncio
    @patch("ee.hogai.graph.entity_search.toolkit.search_entities")
    @patch("ee.hogai.graph.entity_search.toolkit.database_sync_to_async")
    async def test_arun_with_results(self, mock_db_sync, mock_search_entities):
        all_results = [
            {"type": "insight", "result_id": "123", "extra_fields": {"name": "Test Insight"}, "rank": 0.95},
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

        result = await self.toolkit.search(query="test query", entity_types=["insight", "dashboard", "action"])

        assert "Test Insight" in result
        assert "Test Dashboard" in result
        assert "Test Action" in result

        for mock_result in all_results:
            assert self.toolkit.build_url(mock_result["type"], mock_result["result_id"]) in result  # type: ignore

        assert HYPERLINK_USAGE_INSTRUCTIONS in result

    @pytest.mark.asyncio
    @patch("ee.hogai.graph.entity_search.toolkit.database_sync_to_async")
    @patch("ee.hogai.graph.entity_search.toolkit.capture_exception")
    async def test_arun_exception_handling(self, mock_capture, mock_db_sync):
        mock_db_sync.side_effect = Exception("Database error")

        result = await self.toolkit.search(query="test query", entity_types=["insight", "dashboard", "action"])

        assert "Database error" in result

    @pytest.mark.asyncio
    async def test_search_entities_invalid_entity_type(self):
        result = await self.toolkit.search(query="test query", entity_types=["invalid_type"])

        assert "No valid entity types were provided. Will not search for any entity types." in result
