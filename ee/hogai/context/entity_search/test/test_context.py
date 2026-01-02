from posthog.test.base import NonAtomicBaseTest

from django.conf import settings

from parameterized import parameterized

from posthog.models import Action, Cohort, Dashboard, Experiment, FeatureFlag, Insight, Survey

from ee.hogai.context import AssistantContextManager
from ee.hogai.context.entity_search import EntitySearchContext


class TestEntitySearchContext(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.context_manager = AssistantContextManager(self.team, self.user, {})
        self.context = EntitySearchContext(
            team=self.team,
            user=self.user,
            context_manager=self.context_manager,
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
        url = self.context._build_url(entity_type, result_id, self.team.id)
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
        formatted = self.context._get_formatted_entity_result(result)
        for expected_part in expected_parts:
            assert expected_part in formatted

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
        formatted = self.context._get_formatted_entity_result(result)
        assert expected_id_format in formatted

    def test_get_formatted_entity_result_excludes_query_for_insights(self):
        result = {
            "type": "insight",
            "result_id": "123",
            "extra_fields": {"name": "Test Insight", "query": {"kind": "TrendsQuery"}},
        }
        formatted = self.context._get_formatted_entity_result(result)
        assert "query" not in formatted
        assert "TrendsQuery" not in formatted
        assert "Test Insight" in formatted

    def test_get_formatted_entity_result_does_not_exclude_fields_for_other_entities(self):
        result = {
            "type": "cohort",
            "result_id": "456",
            "extra_fields": {"name": "Test Cohort", "filters": {"properties": []}},
        }
        formatted = self.context._get_formatted_entity_result(result)
        assert "filters" in formatted

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
        result = self.context._omit_none_values(input_obj)
        assert result == expected_output

    async def test_insight_filters_exclude_deleted(self):
        await Insight.objects.acreate(
            team=self.team, name="active insight", deleted=False, saved=True, created_by=self.user
        )
        await Insight.objects.acreate(
            team=self.team, name="deleted insight", deleted=True, saved=True, created_by=self.user
        )

        results, _ = await self.context.search_entities({"insight"}, "insight")

        result_names = [r["extra_fields"].get("name", "") for r in results]
        assert "deleted insight" not in result_names

    async def test_insight_filters_exclude_unsaved(self):
        await Insight.objects.acreate(
            team=self.team, name="saved insight", deleted=False, saved=True, created_by=self.user
        )
        await Insight.objects.acreate(
            team=self.team, name="unsaved insight", deleted=False, saved=False, created_by=self.user
        )

        results, _ = await self.context.search_entities({"insight"}, "insight")

        result_names = [r["extra_fields"].get("name", "") for r in results]
        assert "unsaved insight" not in result_names

    async def test_dashboard_filters_exclude_deleted(self):
        await Dashboard.objects.acreate(team=self.team, name="active dashboard", deleted=False, created_by=self.user)
        await Dashboard.objects.acreate(team=self.team, name="deleted dashboard", deleted=True, created_by=self.user)

        results, _ = await self.context.search_entities({"dashboard"}, "dashboard")

        result_names = [r["extra_fields"].get("name", "") for r in results]
        assert "deleted dashboard" not in result_names

    async def test_experiment_filters_exclude_deleted(self):
        flag1 = await FeatureFlag.objects.acreate(team=self.team, key="flag1", created_by=self.user)
        flag2 = await FeatureFlag.objects.acreate(team=self.team, key="flag2", created_by=self.user)
        await Experiment.objects.acreate(
            team=self.team, name="active experiment", deleted=False, created_by=self.user, feature_flag=flag1
        )
        await Experiment.objects.acreate(
            team=self.team, name="deleted experiment", deleted=True, created_by=self.user, feature_flag=flag2
        )

        results, _ = await self.context.search_entities({"experiment"}, "experiment")

        result_names = [r["extra_fields"].get("name", "") for r in results]
        assert "deleted experiment" not in result_names

    async def test_feature_flag_filters_exclude_deleted(self):
        await FeatureFlag.objects.acreate(
            team=self.team, key="active_flag", name="active flag", deleted=False, created_by=self.user
        )
        await FeatureFlag.objects.acreate(
            team=self.team, key="deleted_flag", name="deleted flag", deleted=True, created_by=self.user
        )

        results, _ = await self.context.search_entities({"feature_flag"}, "flag")

        result_keys = [r["extra_fields"].get("key", "") for r in results]
        result_names = [r["extra_fields"].get("name", "") for r in results]
        assert "deleted_flag" not in result_keys
        assert "deleted flag" not in result_names

    async def test_action_filters_exclude_deleted(self):
        await Action.objects.acreate(team=self.team, name="active action", deleted=False, created_by=self.user)
        await Action.objects.acreate(team=self.team, name="deleted action", deleted=True, created_by=self.user)

        results, _ = await self.context.search_entities({"action"}, "action")

        result_names = [r["extra_fields"].get("name", "") for r in results]
        assert "deleted action" not in result_names

    async def test_cohort_filters_exclude_deleted(self):
        await Cohort.objects.acreate(team=self.team, name="active cohort", deleted=False, created_by=self.user)
        await Cohort.objects.acreate(team=self.team, name="deleted cohort", deleted=True, created_by=self.user)

        results, _ = await self.context.search_entities({"cohort"}, "cohort")

        result_names = [r["extra_fields"].get("name", "") for r in results]
        assert "deleted cohort" not in result_names

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

        results, _ = await self.context.search_entities({"survey"}, "survey")

        result_names = [r["extra_fields"].get("name", "") for r in results]
        assert "archived survey" not in result_names

    async def test_all_entity_types_respect_filters_exclude_deleted(self):
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

        results, _ = await self.context.search_entities("all", "deleted")

        result_names = [r["extra_fields"].get("name", "") for r in results]
        assert "deleted insight" not in result_names
        assert "deleted dashboard" not in result_names
        assert "deleted action" not in result_names
        assert "deleted cohort" not in result_names
        assert "archived survey" not in result_names
