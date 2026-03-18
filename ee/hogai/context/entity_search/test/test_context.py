import pytest
from posthog.test.base import NonAtomicBaseTest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from django.conf import settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Action, Cohort, Dashboard, Experiment, FeatureFlag, Insight, Survey
from posthog.models.insight import InsightViewed

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
            ("insight", "test_insight_id", "/project/{team_id}/insights/test_insight_id"),
            ("dashboard", "test_dashboard_id", "/project/{team_id}/dashboard/test_dashboard_id"),
            ("experiment", "test_experiment_id", "/project/{team_id}/experiments/test_experiment_id"),
            ("feature_flag", "test_flag_id", "/project/{team_id}/feature_flags/test_flag_id"),
            ("action", "test_action_id", "/project/{team_id}/data-management/actions/test_action_id"),
            ("cohort", "test_cohort_id", "/project/{team_id}/cohorts/test_cohort_id"),
            ("survey", "test_survey_id", "/project/{team_id}/surveys/test_survey_id"),
            ("error_tracking_issue", "test_issue_id", "/project/{team_id}/error_tracking/test_issue_id"),
            ("notebook", "test_notebook_id", "/project/{team_id}/notebooks/test_notebook_id"),
        ]
    )
    def test_build_url(self, entity_type, result_id, expected_path):
        url = self.context._build_url(entity_type, result_id, self.team.id)
        expected_url = f"{settings.SITE_URL}{expected_path.format(team_id=self.team.id)}"
        assert url == expected_url

    def test_build_url_unknown_entity_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown entity type"):
            self.context._build_url("unknown_type", "123", self.team.id)

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
        assert lines[0] == "entity_type: dashboard"
        assert "dashboard_id|name|description|url" in lines[1]
        assert "456|Test Dashboard|A dashboard|" in lines[2]
        assert "789|Another Dashboard|-|" in lines[3]  # Empty description shows as dash

    def test_format_entities_multiple_types(self):
        entities = [
            {"type": "dashboard", "result_id": "456", "extra_fields": {"name": "Test Dashboard"}},
            {"type": "insight", "result_id": "123", "extra_fields": {"name": "Test Insight"}},
        ]
        formatted = self.context.format_entities(entities)
        lines = formatted.split("\n")
        assert "entity_type|entity_id|name|url" in lines[0]
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

    def test_format_entities_displays_insight_type_when_present(self):
        entities = [
            {
                "type": "insight",
                "result_id": "123",
                "extra_fields": {
                    "name": "Test Insight",
                    "insight_type": "trends",
                },
            },
        ]
        formatted = self.context.format_entities(entities)
        assert "insight_type" in formatted
        assert "trends" in formatted

    @parameterized.expand(
        [
            ("TrendsQuery", "trends"),
            ("FunnelsQuery", "funnels"),
            ("RetentionQuery", "retention"),
            ("PathsQuery", "paths"),
            ("StickinessQuery", "stickiness"),
            ("LifecycleQuery", "lifecycle"),
        ]
    )
    def test_extract_insight_type_strips_query_suffix(self, source_kind, expected):
        # Build a valid InsightVizNode with minimal required fields for each query type
        source: dict = {"kind": source_kind}
        if source_kind == "TrendsQuery":
            source["series"] = []
        elif source_kind == "FunnelsQuery":
            source["series"] = []
            source["funnelsFilter"] = {}
        elif source_kind == "RetentionQuery":
            source["retentionFilter"] = {}
        elif source_kind == "PathsQuery":
            source["pathsFilter"] = {}
        elif source_kind == "StickinessQuery":
            source["series"] = []
            source["stickinessFilter"] = {}
        elif source_kind == "LifecycleQuery":
            source["series"] = []
            source["lifecycleFilter"] = {}
        query = {"kind": "InsightVizNode", "source": source}
        assert self.context._extract_insight_type(query) == expected

    def test_extract_insight_type_returns_none_for_non_insight_viz_node(self):
        assert self.context._extract_insight_type({"kind": "DataTableNode"}) is None
        assert self.context._extract_insight_type({"kind": "TrendsQuery"}) is None
        assert self.context._extract_insight_type(None) is None
        assert self.context._extract_insight_type({}) is None

    def test_format_entities_does_not_exclude_fields_for_other_entities(self):
        entities = [
            {
                "type": "cohort",
                "result_id": "456",
                "extra_fields": {"name": "Test Cohort", "filters": {"properties": []}},
            },
        ]
        formatted = self.context.format_entities(entities)
        assert "filters" in formatted

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

    async def test_list_entities_insight(self):
        insight1 = await Insight.objects.acreate(
            team=self.team, name="List Insight 1", deleted=False, saved=True, created_by=self.user
        )
        insight2 = await Insight.objects.acreate(
            team=self.team, name="List Insight 2", deleted=False, saved=True, created_by=self.user
        )
        # list_entities for insights filters by recent views
        await InsightViewed.objects.acreate(
            team=self.team, user=self.user, insight=insight1, last_viewed_at=timezone.now()
        )
        await InsightViewed.objects.acreate(
            team=self.team, user=self.user, insight=insight2, last_viewed_at=timezone.now()
        )

        entities, total = await self.context.list_entities("insight", limit=10, offset=0)

        assert len(entities) == 2
        assert total == 2
        entity_names = [e["extra_fields"].get("name", "") for e in entities]
        assert "List Insight 1" in entity_names
        assert "List Insight 2" in entity_names

    async def test_list_entities_insight_applies_access_control(self):
        insight1 = await Insight.objects.acreate(
            team=self.team, name="Accessible Insight", deleted=False, saved=True, created_by=self.user
        )
        insight2 = await Insight.objects.acreate(
            team=self.team, name="Restricted Insight", deleted=False, saved=True, created_by=self.user
        )
        await InsightViewed.objects.acreate(
            team=self.team, user=self.user, insight=insight1, last_viewed_at=timezone.now()
        )
        await InsightViewed.objects.acreate(
            team=self.team, user=self.user, insight=insight2, last_viewed_at=timezone.now()
        )

        # Mock filter_queryset_by_access_level to filter out insight2
        def mock_filter(qs):
            return qs.exclude(id=insight2.id)

        with patch.object(
            EntitySearchContext,
            "user_access_control",
            new_callable=PropertyMock,
        ) as mock_uac:
            mock_uac.return_value.filter_queryset_by_access_level = mock_filter

            entities, total = await self.context.list_entities("insight", limit=10, offset=0)

            assert len(entities) == 1
            assert total == 1
            assert entities[0]["extra_fields"]["name"] == "Accessible Insight"

    async def test_list_entities_dashboard(self):
        await Dashboard.objects.acreate(team=self.team, name="List Dashboard", deleted=False, created_by=self.user)

        entities, total = await self.context.list_entities("dashboard", limit=10, offset=0)

        assert len(entities) == 1
        assert total == 1
        assert entities[0]["extra_fields"]["name"] == "List Dashboard"

    async def test_list_entities_pagination(self):
        for i in range(5):
            insight = await Insight.objects.acreate(
                team=self.team, name=f"Paginated Insight {i}", deleted=False, saved=True, created_by=self.user
            )
            # list_entities for insights filters by recent views
            await InsightViewed.objects.acreate(
                team=self.team, user=self.user, insight=insight, last_viewed_at=timezone.now()
            )

        entities_page1, total = await self.context.list_entities("insight", limit=2, offset=0)
        assert len(entities_page1) == 2
        assert total == 5

        entities_page2, total = await self.context.list_entities("insight", limit=2, offset=2)
        assert len(entities_page2) == 2
        assert total == 5

        entities_page3, total = await self.context.list_entities("insight", limit=2, offset=4)
        assert len(entities_page3) == 1
        assert total == 5

    async def test_list_entities_artifact_delegates_to_artifacts_manager(self):
        from posthog.schema import HogQLQuery, VisualizationArtifactContent

        mock_artifacts_manager = MagicMock()
        mock_artifact = MagicMock()
        mock_artifact.artifact_id = "abc123"
        mock_artifact.content = VisualizationArtifactContent(
            name="Test Artifact", description="Test description", query=HogQLQuery(query="SELECT 1")
        )
        mock_artifacts_manager.aget_conversation_artifacts = AsyncMock(return_value=([mock_artifact], 1))

        self.context_manager.artifacts = mock_artifacts_manager

        entities, total = await self.context.list_entities("artifact", limit=10, offset=0)

        mock_artifacts_manager.aget_conversation_artifacts.assert_called_once_with(10, 0)
        assert len(entities) == 1
        assert total == 1
        assert entities[0]["type"] == "artifact"
        assert entities[0]["result_id"] == "abc123"
        assert entities[0]["extra_fields"]["name"] == "Test Artifact"

    async def test_list_entities_artifact_skips_invalid_content(self):
        from pydantic import ValidationError

        mock_artifacts_manager = MagicMock()
        mock_artifact = MagicMock()
        mock_artifact.artifact_id = "invalid123"

        type(mock_artifact).content = PropertyMock(side_effect=ValidationError.from_exception_data("test", []))
        mock_artifacts_manager.aget_conversation_artifacts = AsyncMock(return_value=([mock_artifact], 1))

        self.context_manager.artifacts = mock_artifacts_manager

        entities, total = await self.context.list_entities("artifact", limit=10, offset=0)

        assert len(entities) == 0
        assert total == 1
