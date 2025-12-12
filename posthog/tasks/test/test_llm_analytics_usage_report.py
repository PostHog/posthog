from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseDestroyTablesMixin,
    ClickhouseTestMixin,
    _create_person,
    flush_persons_and_events,
)
from unittest.mock import MagicMock, patch

from posthog.clickhouse.client import sync_execute
from posthog.models import Organization, Team
from posthog.models.event.util import create_event
from posthog.tasks.llm_analytics_usage_report import (
    _get_all_llm_analytics_reports,
    get_all_ai_dimension_breakdowns,
    get_all_ai_metrics,
    get_teams_with_ai_events,
    send_llm_analytics_usage_reports,
)
from posthog.utils import get_previous_day


@freeze_time("2022-01-10T00:01:00Z")
class TestLLMAnalyticsUsageReport(APIBaseTest, ClickhouseTestMixin, ClickhouseDestroyTablesMixin):
    """Tests for LLM Analytics usage reporting functionality."""

    def setUp(self) -> None:
        super().setUp()

        # Stop merges to prevent row collapsing
        sync_execute("SYSTEM STOP MERGES")

        # Clear existing data
        sync_execute("TRUNCATE TABLE events")
        sync_execute("TRUNCATE TABLE person")
        sync_execute("TRUNCATE TABLE person_distinct_id")

    def tearDown(self) -> None:
        sync_execute("SYSTEM START MERGES")
        super().tearDown()

    def _create_ai_events(
        self,
        team: Team,
        distinct_id: str,
        event_type: str,
        count: int,
        properties: dict | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Helper to create AI events."""
        if timestamp is None:
            timestamp = datetime.now(UTC) - timedelta(hours=12)

        base_properties = properties or {}

        for _ in range(count):
            create_event(
                event_uuid=uuid4(),
                distinct_id=distinct_id,
                event=event_type,
                properties=base_properties,
                timestamp=timestamp,
                team=team,
            )

        flush_persons_and_events()

    def test_get_all_ai_metrics(self) -> None:
        """Test that we correctly get all AI metrics in a single combined query."""
        distinct_id = str(uuid4())
        _create_person(distinct_ids=[distinct_id], team=self.team)

        period_start, period_end = get_previous_day()

        # Create different AI event types with various properties
        self._create_ai_events(self.team, distinct_id, "$ai_generation", 5)
        self._create_ai_events(self.team, distinct_id, "$ai_embedding", 3)
        self._create_ai_events(self.team, distinct_id, "$ai_span", 10)
        self._create_ai_events(self.team, distinct_id, "$ai_trace", 2)
        self._create_ai_events(self.team, distinct_id, "$ai_metric", 1)
        self._create_ai_events(self.team, distinct_id, "$ai_feedback", 4)
        self._create_ai_events(self.team, distinct_id, "$ai_evaluation", 6)

        # Create events with cost and token properties
        self._create_ai_events(
            self.team,
            distinct_id,
            "$ai_generation",
            3,
            properties={
                "$ai_total_cost_usd": 0.015,
                "$ai_input_cost_usd": 0.005,
                "$ai_output_cost_usd": 0.010,
                "$ai_request_cost_usd": 0.001,
                "$ai_web_search_cost_usd": 0.002,
                "$ai_input_tokens": 100,
                "$ai_output_tokens": 50,
                "$ai_total_tokens": 150,
                "$ai_reasoning_tokens": 25,
                "$ai_cache_read_input_tokens": 500,
                "$ai_cache_creation_input_tokens": 200,
            },
        )

        # Get team_ids first
        team_ids = get_teams_with_ai_events(period_start, period_end)

        # Get all metrics in one query
        all_metrics = get_all_ai_metrics(period_start, period_end, team_ids)

        # Verify team is in results
        assert self.team.id in all_metrics
        metrics = all_metrics[self.team.id]

        # Verify event counts
        assert metrics.ai_generation_count == 8  # 5 + 3
        assert metrics.ai_embedding_count == 3
        assert metrics.ai_span_count == 10
        assert metrics.ai_trace_count == 2
        assert metrics.ai_metric_count == 1
        assert metrics.ai_feedback_count == 4
        assert metrics.ai_evaluation_count == 6

        # Verify cost metrics (3 events with costs)
        assert metrics.total_cost == pytest.approx(0.045, rel=1e-6)  # 3 * 0.015
        assert metrics.input_cost == pytest.approx(0.015, rel=1e-6)  # 3 * 0.005
        assert metrics.output_cost == pytest.approx(0.030, rel=1e-6)  # 3 * 0.010
        assert metrics.request_cost == pytest.approx(0.003, rel=1e-6)  # 3 * 0.001
        assert metrics.web_search_cost == pytest.approx(0.006, rel=1e-6)  # 3 * 0.002

        # Verify token metrics (3 events with tokens)
        assert metrics.prompt_tokens == 300  # 3 * 100
        assert metrics.completion_tokens == 150  # 3 * 50
        assert metrics.total_tokens == 450  # 3 * 150
        assert metrics.reasoning_tokens == 75  # 3 * 25
        assert metrics.cache_read_tokens == 1500  # 3 * 500
        assert metrics.cache_creation_tokens == 600  # 3 * 200

    def test_get_all_ai_dimension_breakdowns(self) -> None:
        """Test that we correctly get dimension breakdowns using the combined Map-based query."""
        distinct_id = str(uuid4())
        _create_person(distinct_ids=[distinct_id], team=self.team)

        period_start, period_end = get_previous_day()

        # Create AI events with different models and providers
        self._create_ai_events(
            self.team,
            distinct_id,
            "$ai_generation",
            10,
            properties={
                "$ai_model": "gpt-4o-mini",
                "$ai_provider": "openai",
                "$ai_framework": "langchain",
                "$lib": "posthog-python",
            },
        )

        self._create_ai_events(
            self.team,
            distinct_id,
            "$ai_generation",
            5,
            properties={
                "$ai_model": "claude-3-opus",
                "$ai_provider": "anthropic",
                "$lib": "posthog-node",
            },
        )

        self._create_ai_events(
            self.team,
            distinct_id,
            "$ai_embedding",
            3,
            properties={
                "$ai_model": "text-embedding-ada-002",
                "$ai_provider": "openai",
                "$lib": "posthog-python",
            },
        )

        # Get team_ids first
        team_ids = get_teams_with_ai_events(period_start, period_end)

        # Get dimension breakdowns using the new combined function
        all_breakdowns = get_all_ai_dimension_breakdowns(period_start, period_end, team_ids)

        # Verify team is in results
        assert self.team.id in all_breakdowns
        breakdowns = all_breakdowns[self.team.id]

        # Verify model breakdown
        assert breakdowns.model_breakdown.get("gpt-4o-mini") == 10
        assert breakdowns.model_breakdown.get("claude-3-opus") == 5
        assert breakdowns.model_breakdown.get("text-embedding-ada-002") == 3

        # Verify provider breakdown
        assert breakdowns.provider_breakdown.get("openai") == 13  # 10 + 3
        assert breakdowns.provider_breakdown.get("anthropic") == 5

        # Verify framework breakdown
        assert breakdowns.framework_breakdown.get("langchain") == 10
        assert breakdowns.framework_breakdown.get("none") == 8  # 5 + 3 (events without framework)

        # Verify library breakdown
        assert breakdowns.library_breakdown.get("posthog-python") == 13  # 10 + 3
        assert breakdowns.library_breakdown.get("posthog-node") == 5

    def test_get_all_ai_cost_model_breakdowns(self) -> None:
        """Test that we correctly get cost model breakdowns."""
        distinct_id = str(uuid4())
        _create_person(distinct_ids=[distinct_id], team=self.team)

        period_start, period_end = get_previous_day()

        # Create AI events with cost model properties (OpenRouter pricing)
        self._create_ai_events(
            self.team,
            distinct_id,
            "$ai_generation",
            10,
            properties={
                "$ai_model": "gpt-4o-mini",
                "$ai_provider": "openai",
                "$ai_model_cost_used": "openai/gpt-4o-mini",
                "$ai_cost_model_source": "openrouter",
                "$ai_cost_model_provider": "openai",
            },
        )

        # Create AI events with custom pricing
        self._create_ai_events(
            self.team,
            distinct_id,
            "$ai_generation",
            5,
            properties={
                "$ai_model": "my-custom-model",
                "$ai_provider": "custom-provider",
                "$ai_model_cost_used": "custom",
                "$ai_cost_model_source": "custom",
                "$ai_cost_model_provider": "custom",
            },
        )

        # Create AI events with manual pricing
        self._create_ai_events(
            self.team,
            distinct_id,
            "$ai_generation",
            3,
            properties={
                "$ai_model": "claude-3-opus",
                "$ai_provider": "anthropic",
                "$ai_model_cost_used": "anthropic/claude-3-opus",
                "$ai_cost_model_source": "manual",
                "$ai_cost_model_provider": "anthropic",
            },
        )

        # Get team_ids first
        team_ids = get_teams_with_ai_events(period_start, period_end)

        # Get dimension breakdowns using the new combined function
        all_breakdowns = get_all_ai_dimension_breakdowns(period_start, period_end, team_ids)

        # Verify team is in results
        assert self.team.id in all_breakdowns
        breakdowns = all_breakdowns[self.team.id]

        # Verify cost_model_used breakdown
        assert breakdowns.cost_model_used_breakdown.get("openai/gpt-4o-mini") == 10
        assert breakdowns.cost_model_used_breakdown.get("custom") == 5
        assert breakdowns.cost_model_used_breakdown.get("anthropic/claude-3-opus") == 3

        # Verify cost_model_source breakdown
        assert breakdowns.cost_model_source_breakdown.get("openrouter") == 10
        assert breakdowns.cost_model_source_breakdown.get("custom") == 5
        assert breakdowns.cost_model_source_breakdown.get("manual") == 3

        # Verify cost_model_provider breakdown
        assert breakdowns.cost_model_provider_breakdown.get("openai") == 10
        assert breakdowns.cost_model_provider_breakdown.get("custom") == 5
        assert breakdowns.cost_model_provider_breakdown.get("anthropic") == 3

    def test_full_llm_analytics_report(self) -> None:
        """Test the full LLM Analytics report generation."""
        # Create second organization and team
        org_2 = Organization.objects.create(name="Org 2")
        team_2 = Team.objects.create(organization=org_2, name="Team 2")

        distinct_id_1 = str(uuid4())
        distinct_id_2 = str(uuid4())
        _create_person(distinct_ids=[distinct_id_1], team=self.team)
        _create_person(distinct_ids=[distinct_id_2], team=team_2)

        period_start, period_end = get_previous_day()

        # Create comprehensive AI events for team 1
        self._create_ai_events(self.team, distinct_id_1, "$ai_generation", 10)
        self._create_ai_events(self.team, distinct_id_1, "$ai_evaluation", 5)
        self._create_ai_events(
            self.team,
            distinct_id_1,
            "$ai_generation",
            3,
            properties={
                "$ai_total_cost_usd": 0.050,
                "$ai_input_cost_usd": 0.020,
                "$ai_output_cost_usd": 0.030,
                "$ai_request_cost_usd": 0.001,
                "$ai_web_search_cost_usd": 0.002,
                "$ai_input_tokens": 500,
                "$ai_output_tokens": 200,
                "$ai_total_tokens": 700,
                "$ai_reasoning_tokens": 150,
                "$ai_cache_read_input_tokens": 1000,
                "$ai_cache_creation_input_tokens": 500,
                "$ai_model": "gpt-4o-mini",
                "$ai_provider": "openai",
                "$ai_framework": "langchain",
                "$lib": "posthog-python",
                "$ai_model_cost_used": "openai/gpt-4o-mini",
                "$ai_cost_model_source": "openrouter",
                "$ai_cost_model_provider": "openai",
            },
        )

        # Create AI events for team 2
        self._create_ai_events(team_2, distinct_id_2, "$ai_embedding", 7)
        self._create_ai_events(
            team_2,
            distinct_id_2,
            "$ai_generation",
            2,
            properties={
                "$ai_total_cost_usd": 0.025,
                "$ai_input_cost_usd": 0.010,
                "$ai_output_cost_usd": 0.015,
            },
        )

        # Generate reports
        org_reports = _get_all_llm_analytics_reports(period_start, period_end)

        # Verify we have reports for both organizations
        assert len(org_reports) == 2
        assert str(self.organization.id) in org_reports
        assert str(org_2.id) in org_reports

        # Verify org 1 report
        org_1_report = org_reports[str(self.organization.id)]
        assert org_1_report["organization_name"] == self.organization.name
        assert org_1_report["ai_generation_count"] == 13  # 10 + 3
        assert org_1_report["ai_evaluation_count"] == 5
        assert org_1_report["total_ai_cost_usd"] == pytest.approx(0.150, rel=1e-6)  # 3 * 0.050
        assert org_1_report["input_cost_usd"] == pytest.approx(0.060, rel=1e-6)  # 3 * 0.020
        assert org_1_report["output_cost_usd"] == pytest.approx(0.090, rel=1e-6)  # 3 * 0.030
        assert org_1_report["request_cost_usd"] == pytest.approx(0.003, rel=1e-6)  # 3 * 0.001
        assert org_1_report["web_search_cost_usd"] == pytest.approx(0.006, rel=1e-6)  # 3 * 0.002
        assert org_1_report["total_prompt_tokens"] == 1500  # 3 * 500
        assert org_1_report["total_completion_tokens"] == 600  # 3 * 200
        assert org_1_report["total_tokens"] == 2100  # 3 * 700
        assert org_1_report["total_reasoning_tokens"] == 450  # 3 * 150
        assert org_1_report["total_cache_read_tokens"] == 3000  # 3 * 1000
        assert org_1_report["total_cache_creation_tokens"] == 1500  # 3 * 500
        assert org_1_report["model_breakdown"] == {"gpt-4o-mini": 3}
        assert org_1_report["provider_breakdown"] == {"openai": 3}
        assert org_1_report["framework_breakdown"] == {"langchain": 3, "none": 15}
        assert org_1_report["library_breakdown"] == {"posthog-python": 3}
        assert org_1_report["cost_model_used_breakdown"] == {"openai/gpt-4o-mini": 3}
        assert org_1_report["cost_model_source_breakdown"] == {"openrouter": 3}
        assert org_1_report["cost_model_provider_breakdown"] == {"openai": 3}

        # Verify org 2 report
        org_2_report = org_reports[str(org_2.id)]
        assert org_2_report["organization_name"] == org_2.name
        assert org_2_report["ai_embedding_count"] == 7
        assert org_2_report["ai_generation_count"] == 2
        assert org_2_report["total_ai_cost_usd"] == pytest.approx(0.050, rel=1e-6)  # 2 * 0.025

    @patch("posthog.tasks.llm_analytics_usage_report.capture_llm_analytics_report")
    @patch("posthog.tasks.llm_analytics_usage_report.get_ph_client")
    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_send_llm_analytics_usage_reports(
        self,
        mock_feature_enabled: MagicMock,
        mock_get_ph_client: MagicMock,
        mock_capture_report: MagicMock,
    ) -> None:
        """Test the main task to send LLM Analytics usage reports."""
        distinct_id = str(uuid4())
        _create_person(distinct_ids=[distinct_id], team=self.team)

        # Create some AI events
        self._create_ai_events(self.team, distinct_id, "$ai_generation", 5)
        self._create_ai_events(self.team, distinct_id, "$ai_evaluation", 3)

        # Run the task
        send_llm_analytics_usage_reports()

        # Verify capture_llm_analytics_report was called
        assert mock_capture_report.delay.call_count == 1

        # Verify the report data
        call_args = mock_capture_report.delay.call_args
        assert call_args[1]["organization_id"] == str(self.organization.id)
        report_dict = call_args[1]["report_dict"]
        assert report_dict["ai_generation_count"] == 5
        assert report_dict["ai_evaluation_count"] == 3

    def test_no_ai_events_returns_empty_report(self) -> None:
        """Test that when there are no AI events, an empty report is returned."""
        period_start, period_end = get_previous_day()

        # Generate reports without creating any AI events
        org_reports = _get_all_llm_analytics_reports(period_start, period_end)

        # Should return empty dict
        assert len(org_reports) == 0

    def test_multiple_teams_in_same_org(self) -> None:
        """Test that multiple teams in the same org are aggregated correctly."""
        # Create second team in same organization
        team_2 = Team.objects.create(organization=self.organization, name="Team 2")

        distinct_id_1 = str(uuid4())
        distinct_id_2 = str(uuid4())
        _create_person(distinct_ids=[distinct_id_1], team=self.team)
        _create_person(distinct_ids=[distinct_id_2], team=team_2)

        period_start, period_end = get_previous_day()

        # Create events for both teams
        self._create_ai_events(self.team, distinct_id_1, "$ai_generation", 10)
        self._create_ai_events(team_2, distinct_id_2, "$ai_generation", 5)
        self._create_ai_events(self.team, distinct_id_1, "$ai_evaluation", 3)
        self._create_ai_events(team_2, distinct_id_2, "$ai_evaluation", 2)

        # Generate reports
        org_reports = _get_all_llm_analytics_reports(period_start, period_end)

        # Should have one report for the organization
        assert len(org_reports) == 1
        org_report = org_reports[str(self.organization.id)]

        # Counts should be aggregated across both teams
        assert org_report["ai_generation_count"] == 15  # 10 + 5
        assert org_report["ai_evaluation_count"] == 5  # 3 + 2

    def test_dimension_breakdown_aggregation_across_teams(self) -> None:
        """Test that dimension breakdowns are correctly aggregated across teams in the same org."""
        # Create second team in same organization
        team_2 = Team.objects.create(organization=self.organization, name="Team 2")

        distinct_id_1 = str(uuid4())
        distinct_id_2 = str(uuid4())
        _create_person(distinct_ids=[distinct_id_1], team=self.team)
        _create_person(distinct_ids=[distinct_id_2], team=team_2)

        period_start, period_end = get_previous_day()

        # Team 1 uses OpenAI models
        self._create_ai_events(
            self.team,
            distinct_id_1,
            "$ai_generation",
            10,
            properties={
                "$ai_model": "gpt-4o-mini",
                "$ai_provider": "openai",
                "$ai_framework": "langchain",
                "$lib": "posthog-python",
            },
        )

        self._create_ai_events(
            self.team,
            distinct_id_1,
            "$ai_generation",
            5,
            properties={
                "$ai_model": "gpt-4",
                "$ai_provider": "openai",
                "$lib": "posthog-python",
            },
        )

        # Team 2 uses Anthropic models
        self._create_ai_events(
            team_2,
            distinct_id_2,
            "$ai_generation",
            7,
            properties={
                "$ai_model": "claude-3-opus",
                "$ai_provider": "anthropic",
                "$ai_framework": "langchain",
                "$lib": "posthog-node",
            },
        )

        # Team 2 also uses some OpenAI
        self._create_ai_events(
            team_2,
            distinct_id_2,
            "$ai_generation",
            3,
            properties={
                "$ai_model": "gpt-4o-mini",
                "$ai_provider": "openai",
                "$lib": "posthog-python",
            },
        )

        # Generate reports
        org_reports = _get_all_llm_analytics_reports(period_start, period_end)

        # Should have one report for the organization
        assert len(org_reports) == 1
        org_report = org_reports[str(self.organization.id)]

        # Verify model breakdown is aggregated across teams
        assert org_report["model_breakdown"]["gpt-4o-mini"] == 13  # 10 from team1 + 3 from team2
        assert org_report["model_breakdown"]["gpt-4"] == 5  # from team1
        assert org_report["model_breakdown"]["claude-3-opus"] == 7  # from team2

        # Verify provider breakdown is aggregated
        assert org_report["provider_breakdown"]["openai"] == 18  # 10 + 5 + 3
        assert org_report["provider_breakdown"]["anthropic"] == 7

        # Verify framework breakdown is aggregated
        assert org_report["framework_breakdown"]["langchain"] == 17  # 10 + 7
        assert org_report["framework_breakdown"]["none"] == 8  # 5 + 3

        # Verify library breakdown is aggregated
        assert org_report["library_breakdown"]["posthog-python"] == 18  # 10 + 5 + 3
        assert org_report["library_breakdown"]["posthog-node"] == 7

    def test_dimension_breakdowns_filter_empty_values(self) -> None:
        """Test that dimension breakdowns correctly filter out empty and whitespace-only values."""
        distinct_id = str(uuid4())
        _create_person(distinct_ids=[distinct_id], team=self.team)

        period_start, period_end = get_previous_day()

        # Create events with valid dimension values
        self._create_ai_events(
            self.team,
            distinct_id,
            "$ai_generation",
            5,
            properties={
                "$ai_model": "gpt-4o-mini",
                "$ai_provider": "openai",
                "$lib": "posthog-python",
            },
        )

        # Create events with empty model (should be filtered out)
        self._create_ai_events(
            self.team,
            distinct_id,
            "$ai_generation",
            3,
            properties={
                "$ai_model": "",
                "$ai_provider": "anthropic",
                "$lib": "posthog-node",
            },
        )

        # Create events with whitespace-only provider (should be filtered out)
        self._create_ai_events(
            self.team,
            distinct_id,
            "$ai_generation",
            2,
            properties={
                "$ai_model": "claude-3-opus",
                "$ai_provider": "   ",
                "$lib": "posthog-python",
            },
        )

        # Create events with empty library (should be filtered out)
        self._create_ai_events(
            self.team,
            distinct_id,
            "$ai_generation",
            4,
            properties={
                "$ai_model": "gpt-4",
                "$ai_provider": "openai",
                "$lib": "",
            },
        )

        # Create events with no dimension properties at all
        self._create_ai_events(
            self.team,
            distinct_id,
            "$ai_generation",
            1,
            properties={},
        )

        # Get team_ids first
        team_ids = get_teams_with_ai_events(period_start, period_end)

        # Get dimension breakdowns using the new combined function
        all_breakdowns = get_all_ai_dimension_breakdowns(period_start, period_end, team_ids)

        # Verify team is in results
        assert self.team.id in all_breakdowns
        breakdowns = all_breakdowns[self.team.id]

        # Verify model breakdown - should only have valid models
        assert breakdowns.model_breakdown.get("gpt-4o-mini") == 5
        assert breakdowns.model_breakdown.get("claude-3-opus") == 2
        assert breakdowns.model_breakdown.get("gpt-4") == 4
        assert "" not in breakdowns.model_breakdown  # Empty string should be filtered out
        assert breakdowns.model_breakdown.get("") is None

        # Verify provider breakdown - should only have valid providers
        assert breakdowns.provider_breakdown.get("openai") == 9  # 5 + 4
        assert breakdowns.provider_breakdown.get("anthropic") == 3
        assert "" not in breakdowns.provider_breakdown  # Empty string should be filtered out
        assert "   " not in breakdowns.provider_breakdown  # Whitespace should be filtered out
        assert breakdowns.provider_breakdown.get("") is None
        assert breakdowns.provider_breakdown.get("   ") is None

        # Verify library breakdown - should only have valid libraries
        assert breakdowns.library_breakdown.get("posthog-python") == 7  # 5 + 2
        assert breakdowns.library_breakdown.get("posthog-node") == 3
        assert "" not in breakdowns.library_breakdown  # Empty string should be filtered out
        assert breakdowns.library_breakdown.get("") is None

        # Verify framework breakdown - events without framework should count as "none"
        assert breakdowns.framework_breakdown.get("none") == 15  # All events (3+2+4+1+5) have no framework

    def test_get_teams_with_ai_events(self) -> None:
        """Test that get_teams_with_ai_events returns correct team IDs."""
        # Create second team
        org_2 = Organization.objects.create(name="Org 2")
        team_2 = Team.objects.create(organization=org_2, name="Team 2")
        team_3 = Team.objects.create(organization=self.organization, name="Team 3 - no events")

        distinct_id_1 = str(uuid4())
        distinct_id_2 = str(uuid4())
        _create_person(distinct_ids=[distinct_id_1], team=self.team)
        _create_person(distinct_ids=[distinct_id_2], team=team_2)

        period_start, period_end = get_previous_day()

        # Create AI events for team 1 and team 2, but not team 3
        self._create_ai_events(self.team, distinct_id_1, "$ai_generation", 5)
        self._create_ai_events(team_2, distinct_id_2, "$ai_embedding", 3)

        # Get teams with AI events
        team_ids = get_teams_with_ai_events(period_start, period_end)

        # Verify correct teams are returned
        assert self.team.id in team_ids
        assert team_2.id in team_ids
        assert team_3.id not in team_ids
        assert len(team_ids) == 2

    @patch("posthog.tasks.llm_analytics_usage_report.capture_llm_analytics_report")
    @patch("posthog.tasks.llm_analytics_usage_report.get_ph_client")
    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_send_llm_analytics_usage_reports_dry_run(
        self,
        mock_feature_enabled: MagicMock,
        mock_get_ph_client: MagicMock,
        mock_capture_report: MagicMock,
    ) -> None:
        """Test that dry_run=True prevents reports from being sent."""
        distinct_id = str(uuid4())
        _create_person(distinct_ids=[distinct_id], team=self.team)

        # Create some AI events
        self._create_ai_events(self.team, distinct_id, "$ai_generation", 5)

        # Run the task with dry_run=True
        send_llm_analytics_usage_reports(dry_run=True)

        # Verify capture_llm_analytics_report was NOT called
        assert mock_capture_report.delay.call_count == 0

    @patch("posthog.tasks.llm_analytics_usage_report.capture_llm_analytics_report")
    @patch("posthog.tasks.llm_analytics_usage_report._get_all_llm_analytics_reports")
    @patch("posthoganalytics.capture_exception")
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_send_llm_analytics_usage_reports_disabled_by_feature_flag(
        self,
        mock_feature_enabled: MagicMock,
        mock_capture_exception: MagicMock,
        mock_get_reports: MagicMock,
        mock_capture_report: MagicMock,
    ) -> None:
        """Test that reports are not sent when disabled by feature flag."""
        # Run the task
        send_llm_analytics_usage_reports()

        # Verify feature flag was checked
        mock_feature_enabled.assert_called_once_with("llm-analytics-disable-usage-reports", "internal_billing_events")

        # Verify capture_exception was called to log that reports are disabled
        assert mock_capture_exception.call_count == 1

        # Verify _get_all_llm_analytics_reports was NOT called (early exit)
        assert mock_get_reports.call_count == 0

        # Verify capture_llm_analytics_report was NOT called
        assert mock_capture_report.delay.call_count == 0

    @patch("posthog.tasks.llm_analytics_usage_report.capture_llm_analytics_report")
    @patch("posthog.tasks.llm_analytics_usage_report.get_ph_client")
    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_send_llm_analytics_usage_reports_with_at_parameter(
        self,
        mock_feature_enabled: MagicMock,
        mock_get_ph_client: MagicMock,
        mock_capture_report: MagicMock,
    ) -> None:
        """Test that the at parameter correctly specifies the report date."""
        distinct_id = str(uuid4())
        _create_person(distinct_ids=[distinct_id], team=self.team)

        # Create AI events for January 5th (within Jan 4th period when at="2022-01-05")
        jan_5_timestamp = datetime(2022, 1, 5, 12, 0, 0, tzinfo=UTC)
        self._create_ai_events(
            self.team,
            distinct_id,
            "$ai_generation",
            5,
            timestamp=jan_5_timestamp,
        )

        # Create AI events for January 9th (within the default period based on freeze_time)
        jan_9_timestamp = datetime(2022, 1, 9, 12, 0, 0, tzinfo=UTC)
        self._create_ai_events(
            self.team,
            distinct_id,
            "$ai_embedding",
            3,
            timestamp=jan_9_timestamp,
        )

        # Run the task with at="2022-01-06" (reports for Jan 5th)
        send_llm_analytics_usage_reports(at="2022-01-06")

        # Verify capture_llm_analytics_report was called
        assert mock_capture_report.delay.call_count == 1

        # Verify only Jan 5th events are in the report (not Jan 9th)
        call_args = mock_capture_report.delay.call_args
        report_dict = call_args[1]["report_dict"]
        assert report_dict["ai_generation_count"] == 5
        assert report_dict["ai_embedding_count"] == 0  # Jan 9th events not included
