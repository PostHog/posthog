import pytest
from unittest.mock import AsyncMock, Mock, patch

from parameterized import parameterized

from ee.hogai.graph.entity_search.toolkit import HYPERLINK_USAGE_INSTRUCTIONS, EntitySearchToolkit


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

        content = self.toolkit._format_results_for_display(
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
        result = await self.toolkit.search_entities(query=None, entity_types=["insight", "dashboard", "action"])

        assert "No search query was provided" in result

    @pytest.mark.asyncio
    @patch("ee.hogai.graph.entity_search.toolkit.class_queryset")
    @patch("ee.hogai.graph.entity_search.toolkit.database_sync_to_async")
    async def test_arun_with_results(self, mock_db_sync, mock_class_queryset):
        all_results = [
            {"type": "insight", "result_id": "123", "extra_fields": {"name": "Test Insight"}, "rank": 0.95},
            {"type": "dashboard", "result_id": "456", "extra_fields": {"name": "Test Dashboard"}, "rank": 0.90},
            {"type": "action", "result_id": "101", "extra_fields": {"name": "Test Action"}, "rank": 0.80},
        ]

        call_count = 0
        entity_types_order = ["insight", "dashboard", "action"]

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

        result = await self.toolkit.search_entities(query="test query", entity_types=["insight", "dashboard", "action"])

        assert "Test Insight" in result
        assert "Test Dashboard" in result
        assert "Test Action" in result

        for mock_result in all_results:
            assert self.toolkit.build_url(mock_result["type"], mock_result["result_id"]) in result

        assert HYPERLINK_USAGE_INSTRUCTIONS in result

    @pytest.mark.asyncio
    @patch("ee.hogai.graph.entity_search.toolkit.class_queryset")
    @patch("ee.hogai.graph.entity_search.toolkit.database_sync_to_async")
    @patch("ee.hogai.graph.entity_search.toolkit.capture_exception")
    async def test_arun_exception_handling(self, mock_capture, mock_db_sync, mock_class_queryset):
        mock_db_sync.side_effect = Exception("Database error")

        result = await self.toolkit.search_entities(query="test query", entity_types=["insight", "dashboard", "action"])

        assert "Database error" in result

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
        results = await self.toolkit._gather_bounded(5, coros)

        assert len(results) == 20
        assert max_concurrent <= 5

    @pytest.mark.asyncio
    async def test_search_entities_invalid_entity_type(self):
        result = await self.toolkit.search_entities(query="test query", entity_types=["invalid_type"])

        assert "Invalid entity type: invalid_type. Will not search for this entity type." in result
