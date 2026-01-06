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

    def test_format_entities_single_type(self):
        entities = [
            {
                "type": "dashboard",
                "result_id": "456",
                "extra_fields": {"name": "Test Dashboard", "description": "A dashboard"},
            },
            {"type": "dashboard", "result_id": "789", "extra_fields": {"name": "Another Dashboard"}},
        ]
        formatted = self.context.format_entities(entities)
        lines = formatted.split("\n")
        assert lines[0] == "Entity type: Dashboard"
        assert "ID|Name|Description|URL" in lines[1]
        assert "456|Test Dashboard|A dashboard|" in lines[2]
        assert "789|Another Dashboard|-|" in lines[3]  # Empty description shows as dash

    def test_format_entities_multiple_types(self):
        entities = [
            {"type": "dashboard", "result_id": "456", "extra_fields": {"name": "Test Dashboard"}},
            {"type": "insight", "result_id": "123", "extra_fields": {"name": "Test Insight"}},
        ]
        formatted = self.context.format_entities(entities)
        lines = formatted.split("\n")
        assert "Entity type|ID|Name|URL" in lines[0]
        assert "Dashboard|456|Test Dashboard|" in lines[1]
        assert "Insight|123|Test Insight|" in lines[2]

    def test_format_entities_includes_id(self):
        entities = [
            {"type": "dashboard", "result_id": "456", "extra_fields": {"name": "Test Dashboard"}},
        ]
        formatted = self.context.format_entities(entities)
        assert "456|Test Dashboard|" in formatted

    def test_format_entities_excludes_query_for_insights(self):
        entities = [
            {
                "type": "insight",
                "result_id": "123",
                "extra_fields": {"name": "Test Insight", "query": {"kind": "TrendsQuery"}},
            },
        ]
        formatted = self.context.format_entities(entities)
        assert "TrendsQuery" not in formatted
        assert "Test Insight" in formatted

    def test_format_entities_does_not_exclude_fields_for_other_entities(self):
        entities = [
            {
                "type": "cohort",
                "result_id": "456",
                "extra_fields": {"name": "Test Cohort", "filters": {"properties": []}},
            },
        ]
        formatted = self.context.format_entities(entities)
        assert "Filters" in formatted

    def test_format_entities_escapes_pipe_characters(self):
        entities = [
            {
                "type": "dashboard",
                "result_id": "456",
                "extra_fields": {"name": "Test|Dashboard", "description": "Has|pipes"},
            },
        ]
        formatted = self.context.format_entities(entities)
        assert '"Test|Dashboard"' in formatted
        assert '"Has|pipes"' in formatted

    def test_format_entities_empty_list(self):
        formatted = self.context.format_entities([])
        assert formatted == ""

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
