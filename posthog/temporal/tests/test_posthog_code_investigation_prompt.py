"""Tests for the report schema and prompt builder in
posthog/temporal/alerts/posthog_code_investigation.py.
"""

from posthog.test.base import BaseTest

import pydantic

from posthog.models import Organization, Team
from posthog.temporal.alerts.posthog_code_investigation import (
    AlertInvestigationReport,
    build_investigation_prompt,
    list_team_investigation_skills,
)

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.product_analytics.backend.models.insight import Insight
from products.skills.backend.models.skills import LLMSkill


def _make_alert(team, insight, **kwargs) -> AlertConfiguration:
    defaults: dict = {
        "name": "Error rate spike",
        "investigation_mode": AlertConfiguration.InvestigationMode.POSTHOG_CODE,
        "investigation_agent_enabled": True,
    }
    defaults.update(kwargs)
    return AlertConfiguration.objects.create(team=team, insight=insight, **defaults)


def _make_check(alert, *, calculated_value: float = 42.0) -> AlertCheck:
    return AlertCheck.objects.create(
        alert_configuration=alert,
        calculated_value=calculated_value,
    )


def _firing_context(alert_check: AlertCheck, *, dashboard_ids: list[int] | None = None) -> dict:
    return {
        "alert_check_id": str(alert_check.id),
        "calculated_value": alert_check.calculated_value,
        "threshold_lower": 10.0,
        "threshold_upper": 30.0,
        "dashboard_ids": dashboard_ids or [],
    }


class TestAlertInvestigationReport(BaseTest):
    def test_valid_report_parses(self) -> None:
        report = AlertInvestigationReport(
            findings="Error rate doubled.",
            suspected_cause="Bad deploy at 14:00.",
            proposed_mitigation="Roll back deploy abc123.",
            confidence=0.85,
            verdict="true_positive",
        )
        assert report.verdict == "true_positive"
        assert report.pr_url is None

    def test_pr_url_optional(self) -> None:
        report = AlertInvestigationReport(
            findings="f",
            suspected_cause="c",
            proposed_mitigation="m",
            confidence=0.5,
            verdict="inconclusive",
            pr_url="https://github.com/org/repo/pull/1",
        )
        assert report.pr_url == "https://github.com/org/repo/pull/1"

    def test_confidence_bounds(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            AlertInvestigationReport(
                findings="f",
                suspected_cause="c",
                proposed_mitigation="m",
                confidence=1.1,
                verdict="true_positive",
            )
        with self.assertRaises(pydantic.ValidationError):
            AlertInvestigationReport(
                findings="f",
                suspected_cause="c",
                proposed_mitigation="m",
                confidence=-0.1,
                verdict="true_positive",
            )

    def test_verdict_field_description_covers_semantics(self) -> None:
        # Both false_positive and true_positive semantics must appear somewhere in the schema.
        schema_json = AlertInvestigationReport.model_json_schema()
        schema_str = str(schema_json)
        assert "false_positive" in schema_str
        assert "true_positive" in schema_str


class TestBuildInvestigationPrompt(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="Checkout funnel")
        self.alert = _make_alert(self.team, self.insight, investigation_context="Focus on the payment step.")
        self.check = _make_check(self.alert)
        self.ctx = _firing_context(self.check, dashboard_ids=[101, 202])

    def test_prompt_contains_alert_name(self) -> None:
        prompt = build_investigation_prompt(
            self.alert,
            self.check,
            firing_context=self.ctx,
            skill_names=[],
            previous_task_run_id=None,
        )
        assert self.alert.name in prompt

    def test_prompt_contains_breach_values(self) -> None:
        prompt = build_investigation_prompt(
            self.alert,
            self.check,
            firing_context=self.ctx,
            skill_names=[],
            previous_task_run_id=None,
        )
        assert str(self.ctx["alert_check_id"]) in prompt
        assert str(self.ctx["calculated_value"]) in prompt

    def test_prompt_contains_insight_short_id(self) -> None:
        prompt = build_investigation_prompt(
            self.alert,
            self.check,
            firing_context=self.ctx,
            skill_names=[],
            previous_task_run_id=None,
        )
        assert self.insight.short_id in prompt

    def test_prompt_contains_dashboard_deep_links(self) -> None:
        prompt = build_investigation_prompt(
            self.alert,
            self.check,
            firing_context=self.ctx,
            skill_names=[],
            previous_task_run_id=None,
        )
        assert "/dashboard/101" in prompt
        assert "/dashboard/202" in prompt

    def test_prompt_contains_insight_dashboard_filters_caveat(self) -> None:
        prompt = build_investigation_prompt(
            self.alert,
            self.check,
            firing_context=self.ctx,
            skill_names=[],
            previous_task_run_id=None,
        )
        # Caveat: insight uses its own config; dashboard may differ
        assert "own configuration" in prompt

    def test_prompt_names_baseline_skill(self) -> None:
        prompt = build_investigation_prompt(
            self.alert,
            self.check,
            firing_context=self.ctx,
            skill_names=[],
            previous_task_run_id=None,
        )
        assert "investigating-alert-firings" in prompt

    def test_prompt_lists_team_skills(self) -> None:
        prompt = build_investigation_prompt(
            self.alert,
            self.check,
            firing_context=self.ctx,
            skill_names=["investigation-slo", "investigation-latency"],
            previous_task_run_id=None,
        )
        assert "investigation-slo" in prompt
        assert "investigation-latency" in prompt

    def test_prompt_contains_owner_instructions_when_context_set(self) -> None:
        prompt = build_investigation_prompt(
            self.alert,
            self.check,
            firing_context=self.ctx,
            skill_names=[],
            previous_task_run_id=None,
        )
        assert "Alert owner's instructions" in prompt
        assert "Focus on the payment step." in prompt

    def test_no_owner_instructions_heading_without_context(self) -> None:
        alert = _make_alert(self.team, self.insight, investigation_context=None)
        check = _make_check(alert)
        ctx = _firing_context(check)
        prompt = build_investigation_prompt(
            alert,
            check,
            firing_context=ctx,
            skill_names=[],
            previous_task_run_id=None,
        )
        assert "Alert owner's instructions" not in prompt

    def test_prompt_links_previous_run_on_rerun(self) -> None:
        prompt = build_investigation_prompt(
            self.alert,
            self.check,
            firing_context=self.ctx,
            skill_names=[],
            previous_task_run_id="abc-123",
        )
        assert "abc-123" in prompt

    def test_no_previous_run_section_without_id(self) -> None:
        prompt = build_investigation_prompt(
            self.alert,
            self.check,
            firing_context=self.ctx,
            skill_names=[],
            previous_task_run_id=None,
        )
        # Should not contain rerun language when there's no previous run
        assert "re-run" not in prompt.lower()

    def test_prompt_contains_structured_output_instruction(self) -> None:
        prompt = build_investigation_prompt(
            self.alert,
            self.check,
            firing_context=self.ctx,
            skill_names=[],
            previous_task_run_id=None,
        )
        assert "structured output" in prompt.lower()

    def test_empty_dashboard_ids_produces_no_dashboard_links(self) -> None:
        alert = _make_alert(self.team, self.insight)
        check = _make_check(alert)
        ctx = _firing_context(check, dashboard_ids=[])
        prompt = build_investigation_prompt(
            alert,
            check,
            firing_context=ctx,
            skill_names=[],
            previous_task_run_id=None,
        )
        assert "/dashboard/" not in prompt

    def test_threshold_bounds_appear_when_set(self) -> None:
        prompt = build_investigation_prompt(
            self.alert,
            self.check,
            firing_context=self.ctx,
            skill_names=[],
            previous_task_run_id=None,
        )
        assert "10.0" in prompt
        assert "30.0" in prompt


class TestListTeamInvestigationSkills(BaseTest):
    def test_lists_prefix_matches_only(self) -> None:
        LLMSkill.objects.create(team=self.team, name="investigation-slo", description="d", body="b")
        LLMSkill.objects.create(team=self.team, name="signals-scout-x", description="d", body="b")
        names = list_team_investigation_skills(self.team.pk)
        assert names == ["investigation-slo"]

    def test_stamps_category_on_empty_category_rows(self) -> None:
        LLMSkill.objects.create(team=self.team, name="investigation-latency", description="d", body="b", category="")
        list_team_investigation_skills(self.team.pk)
        assert LLMSkill.objects.get(name="investigation-latency", team=self.team).category == "investigation"

    def test_does_not_overwrite_existing_category(self) -> None:
        LLMSkill.objects.create(
            team=self.team, name="investigation-custom", description="d", body="b", category="scout"
        )
        list_team_investigation_skills(self.team.pk)
        # category was already set; should not be overwritten (filter targets empty string)
        assert LLMSkill.objects.get(name="investigation-custom", team=self.team).category == "scout"

    def test_excludes_deleted_skills(self) -> None:
        LLMSkill.objects.create(team=self.team, name="investigation-old", description="d", body="b", deleted=True)
        names = list_team_investigation_skills(self.team.pk)
        assert "investigation-old" not in names

    def test_excludes_non_latest_skills(self) -> None:
        LLMSkill.objects.create(team=self.team, name="investigation-v1", description="d", body="b", is_latest=False)
        names = list_team_investigation_skills(self.team.pk)
        assert "investigation-v1" not in names

    def test_excludes_other_teams_skills(self) -> None:
        org2 = Organization.objects.create(name="Other Org")
        team2 = Team.objects.create(organization=org2, name="Other Team")
        LLMSkill.objects.create(team=team2, name="investigation-other", description="d", body="b")
        names = list_team_investigation_skills(self.team.pk)
        assert "investigation-other" not in names

    def test_returns_sorted_names(self) -> None:
        LLMSkill.objects.create(team=self.team, name="investigation-zzz", description="d", body="b")
        LLMSkill.objects.create(team=self.team, name="investigation-aaa", description="d", body="b")
        names = list_team_investigation_skills(self.team.pk)
        assert names == sorted(names)
