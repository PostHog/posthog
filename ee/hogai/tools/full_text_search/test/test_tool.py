from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.conf import settings

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.models import Action, Cohort, Dashboard, Experiment, FeatureFlag, Insight, Survey

from ee.hogai.context import AssistantContextManager
from ee.hogai.core.shared_prompts import HYPERLINK_USAGE_INSTRUCTIONS
from ee.hogai.tools.full_text_search.tool import ENTITY_MAP, EntitySearchTool, FTSKind
from ee.hogai.utils.types.base import AssistantState


class TestEntitySearchToolkit(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()

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

    @parameterized.expand(
        [
            ("dashboard", "456", "dashboard_id: '456'"),
            ("cohort", "789", "cohort_id: '789'"),
            ("insight", "123", "insight_id: '123'"),
            ("action", "101", "action_id: '101'"),
            ("feature_flag", "202", "feature_flag_id: '202'"),
        ]
    )
    def test_get_formatted_entity_result_uses_entity_specific_id(self, entity_type, result_id, expected_id_format):
        result = {"type": entity_type, "result_id": result_id, "extra_fields": {"name": f"Test {entity_type}"}}
        formatted = self.toolkit._get_formatted_entity_result(result)
        assert expected_id_format in formatted

    def test_get_formatted_entity_result_excludes_query_for_insights(self):
        result = {
            "type": "insight",
            "result_id": "123",
            "extra_fields": {"name": "Test Insight", "query": {"kind": "TrendsQuery"}},
        }
        formatted = self.toolkit._get_formatted_entity_result(result)
        assert "query" not in formatted
        assert "TrendsQuery" not in formatted
        assert "Test Insight" in formatted

    def test_get_formatted_entity_result_does_not_exclude_fields_for_other_entities(self):
        result = {
            "type": "cohort",
            "result_id": "456",
            "extra_fields": {"name": "Test Cohort", "filters": {"properties": []}},
        }
        formatted = self.toolkit._get_formatted_entity_result(result)
        assert "filters" in formatted

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

    @patch("ee.hogai.tools.full_text_search.tool.search_entities")
    async def test_search_no_entity_types(self, mock_search_entities):
        all_results: list[dict] = [
            {"type": "cohort", "result_id": "123", "extra_fields": {"name": "Test cohort"}, "rank": 0.95},
            {"type": "dashboard", "result_id": "456", "extra_fields": {"name": "Test Dashboard"}, "rank": 0.90},
            {"type": "action", "result_id": "101", "extra_fields": {"name": "Test Action"}, "rank": 0.80},
        ]

        def side_effect_func(entities, query, project_id, view, entity_map):
            return (all_results, dict.fromkeys(entities, 1))

        mock_search_entities.side_effect = side_effect_func

        _ = await self.toolkit.execute(query="test query", search_kind=FTSKind.ALL)

        mock_search_entities.assert_called_once_with(
            set(ENTITY_MAP.keys()), "test query", self.team.project_id, self.toolkit, ENTITY_MAP
        )

    @patch("ee.hogai.tools.full_text_search.tool.search_entities")
    async def test_arun_with_results(self, mock_search_entities):
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

        mock_search_entities.side_effect = side_effect_func

        for expected_result in all_results:
            result = await self.toolkit.execute(query="test query", search_kind=expected_result["kind"])
            assert expected_result["type"] in result
            assert expected_result["extra_fields"]["name"] in result
            assert self.toolkit._build_url(expected_result["type"], expected_result["result_id"]) in result
            assert HYPERLINK_USAGE_INSTRUCTIONS in result

    @patch("ee.hogai.tools.full_text_search.tool.database_sync_to_async")
    @patch("ee.hogai.tools.full_text_search.tool.capture_exception")
    async def test_arun_exception_handling(self, mock_capture, mock_db_sync):
        mock_db_sync.side_effect = Exception("Database error")

        result = await self.toolkit.execute(query="test query", search_kind=FTSKind.DASHBOARDS)

        assert "Database error" in result

    async def test_search_entities_invalid_entity_type(self):
        result = await self.toolkit.execute(query="test query", search_kind="invalid_type")  # type: ignore

        assert "Invalid entity kind: invalid_type. Will not perform search for it." in result

    @parameterized.expand(
        [
            ({"a": 1, "b": None, "c": 3}, {"a": 1, "c": 3}),
            ({"nested": {"x": 1, "y": None, "z": 2}}, {"nested": {"x": 1, "z": 2}}),
            ({"list": [1, None, 3, None, 5]}, {"list": [1, 3, 5]}),
            ({"tuple": (1, None, 3)}, {"tuple": (1, 3)}),
            (
                {"a": {"b": {"c": None, "d": 4}}, "e": [None, {"f": None, "g": 7}]},
                {"a": {"b": {"d": 4}}, "e": [{"g": 7}]},
            ),
            ({"empty_dict": {}, "empty_list": []}, {"empty_dict": {}, "empty_list": []}),
            ({"all_none": None}, {}),
            ({}, {}),
            ([], []),
        ]
    )
    def test_omit_none_values(self, input_obj, expected_output):
        result = self.toolkit._omit_none_values(input_obj)
        assert result == expected_output

    async def test_insight_filters_exclude_deleted(self):
        await Insight.objects.acreate(
            team=self.team, name="active insight", deleted=False, saved=True, created_by=self.user
        )
        await Insight.objects.acreate(
            team=self.team, name="deleted insight", deleted=True, saved=True, created_by=self.user
        )

        result = await self.toolkit.execute(query="insight", search_kind=FTSKind.INSIGHTS)

        # Deleted insights should not appear
        assert "deleted insight" not in result

    async def test_insight_filters_exclude_unsaved(self):
        await Insight.objects.acreate(
            team=self.team, name="saved insight", deleted=False, saved=True, created_by=self.user
        )
        await Insight.objects.acreate(
            team=self.team, name="unsaved insight", deleted=False, saved=False, created_by=self.user
        )

        result = await self.toolkit.execute(query="insight", search_kind=FTSKind.INSIGHTS)

        # Unsaved insights should not appear
        assert "unsaved insight" not in result

    async def test_dashboard_filters_exclude_deleted(self):
        await Dashboard.objects.acreate(team=self.team, name="active dashboard", deleted=False, created_by=self.user)
        await Dashboard.objects.acreate(team=self.team, name="deleted dashboard", deleted=True, created_by=self.user)

        result = await self.toolkit.execute(query="dashboard", search_kind=FTSKind.DASHBOARDS)

        assert "deleted dashboard" not in result

    async def test_experiment_filters_exclude_deleted(self):
        flag1 = await FeatureFlag.objects.acreate(team=self.team, key="flag1", created_by=self.user)
        flag2 = await FeatureFlag.objects.acreate(team=self.team, key="flag2", created_by=self.user)
        await Experiment.objects.acreate(
            team=self.team, name="active experiment", deleted=False, created_by=self.user, feature_flag=flag1
        )
        await Experiment.objects.acreate(
            team=self.team, name="deleted experiment", deleted=True, created_by=self.user, feature_flag=flag2
        )

        result = await self.toolkit.execute(query="experiment", search_kind=FTSKind.EXPERIMENTS)

        assert "deleted experiment" not in result

    async def test_feature_flag_filters_exclude_deleted(self):
        await FeatureFlag.objects.acreate(
            team=self.team, key="active_flag", name="active flag", deleted=False, created_by=self.user
        )
        await FeatureFlag.objects.acreate(
            team=self.team, key="deleted_flag", name="deleted flag", deleted=True, created_by=self.user
        )

        result = await self.toolkit.execute(query="flag", search_kind=FTSKind.FEATURE_FLAGS)

        assert "deleted_flag" not in result
        assert "deleted" not in result.lower() or "active" in result.lower()

    async def test_action_filters_exclude_deleted(self):
        await Action.objects.acreate(team=self.team, name="active action", deleted=False, created_by=self.user)
        await Action.objects.acreate(team=self.team, name="deleted action", deleted=True, created_by=self.user)

        result = await self.toolkit.execute(query="action", search_kind=FTSKind.ACTIONS)

        assert "deleted action" not in result

    async def test_cohort_filters_exclude_deleted(self):
        await Cohort.objects.acreate(team=self.team, name="active cohort", deleted=False, created_by=self.user)
        await Cohort.objects.acreate(team=self.team, name="deleted cohort", deleted=True, created_by=self.user)

        result = await self.toolkit.execute(query="cohort", search_kind=FTSKind.COHORTS)

        assert "deleted cohort" not in result

    async def test_survey_filters_exclude_archived(self):
        await Survey.objects.acreate(
            team=self.team,
            name="active survey",
            archived=False,
            created_by=self.user,
            type=Survey.SurveyType.POPOVER,
        )
        await Survey.objects.acreate(
            team=self.team,
            name="archived survey",
            archived=True,
            created_by=self.user,
            type=Survey.SurveyType.POPOVER,
        )

        result = await self.toolkit.execute(query="survey", search_kind=FTSKind.SURVEYS)

        assert "archived survey" not in result

    async def test_all_entity_types_respect_filters_exclude_deleted(self):
        # Create deleted items across multiple entity types
        await Insight.objects.acreate(
            team=self.team, name="deleted insight", deleted=True, saved=True, created_by=self.user
        )
        await Dashboard.objects.acreate(team=self.team, name="deleted dashboard", deleted=True, created_by=self.user)
        await Action.objects.acreate(team=self.team, name="deleted action", deleted=True, created_by=self.user)
        await Cohort.objects.acreate(team=self.team, name="deleted cohort", deleted=True, created_by=self.user)
        await Survey.objects.acreate(
            team=self.team,
            name="archived survey",
            archived=True,
            created_by=self.user,
            type=Survey.SurveyType.POPOVER,
        )

        result = await self.toolkit.execute(query="deleted", search_kind=FTSKind.ALL)

        # All deleted/archived items should be filtered out
        assert "deleted insight" not in result
        assert "deleted dashboard" not in result
        assert "deleted action" not in result
        assert "deleted cohort" not in result
        assert "archived survey" not in result
