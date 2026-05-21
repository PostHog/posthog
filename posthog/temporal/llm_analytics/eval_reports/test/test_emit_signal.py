import random

import pytest
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team
from posthog.temporal.llm_analytics.eval_reports.emit_signal import (
    EmitEvalReportSignalInputs,
    EvalReportSignalSummary,
    _build_eval_report_signal_prompt,
    emit_eval_report_signal_activity,
)

from products.signals.backend.models import SignalSourceConfig


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"SignalsEvalReportOrg-{random.randint(1, 99999)}",
        is_ai_data_processing_approved=True,
    )
    yield organization
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsEvalReportTeam-{random.randint(1, 99999)}",
    )
    yield team
    await sync_to_async(team.delete)()


def _make_content() -> dict:
    return {
        "title": "Pass rate dropped 14pp on the cost-cap eval",
        "sections": [
            {"title": "Summary", "content": "Pass rate dropped from 86% to 72%."},
            {"title": "Patterns", "content": "Failures concentrated on gpt-5-mini."},
        ],
        "citations": [
            {"generation_id": "gen-1", "reason": "Example high-cost failure"},
        ],
        "metrics": {
            "total_runs": 1024,
            "pass_count": 737,
            "fail_count": 283,
            "na_count": 4,
            "pass_rate": 72.25,
            "previous_pass_rate": 86.12,
        },
    }


def _make_inputs(team_id: int, evaluation_id: str = "eval-123") -> EmitEvalReportSignalInputs:
    return EmitEvalReportSignalInputs(
        team_id=team_id,
        evaluation_id=evaluation_id,
        evaluation_name="Cost cap check",
        evaluation_description="Flag generations above the cost cap",
        evaluation_prompt="Return true if cost > 0.05",
        report_id="report-abc",
        report_run_id="run-xyz",
        period_start="2026-04-01T00:00:00+00:00",
        period_end="2026-04-02T00:00:00+00:00",
    )


class TestBuildEvalReportSignalPrompt:
    def test_includes_evaluation_metadata(self):
        inputs = _make_inputs(team_id=1)
        prompt = _build_eval_report_signal_prompt(inputs, _make_content())
        assert "Cost cap check" in prompt
        assert "Flag generations above the cost cap" in prompt
        assert "Return true if cost > 0.05" in prompt

    def test_includes_period_and_content(self):
        inputs = _make_inputs(team_id=1)
        prompt = _build_eval_report_signal_prompt(inputs, _make_content())
        assert "2026-04-01T00:00:00+00:00" in prompt
        assert "2026-04-02T00:00:00+00:00" in prompt
        # Report title and a section body should both appear since we dump the full content
        assert "Pass rate dropped 14pp on the cost-cap eval" in prompt
        assert "Pass rate dropped from 86% to 72%." in prompt

    def test_omits_empty_description_and_prompt_cleanly(self):
        inputs = _make_inputs(team_id=1)
        inputs.evaluation_description = ""
        inputs.evaluation_prompt = ""
        prompt = _build_eval_report_signal_prompt(inputs, _make_content())
        # Header label should only appear when the value is present
        assert "EVALUATION DESCRIPTION" not in prompt
        assert "EVALUATION PROMPT" not in prompt
        assert "Cost cap check" in prompt


async def _setup_no_source_config(ateam):
    del ateam


async def _setup_evaluation_not_in_allowlist(ateam):
    await sync_to_async(SignalSourceConfig.objects.create)(
        team=ateam,
        source_product=SignalSourceConfig.SourceProduct.LLM_ANALYTICS,
        source_type=SignalSourceConfig.SourceType.EVALUATION,
        enabled=True,
        config={"evaluation_ids": ["other-eval"]},
    )


async def _setup_config_disabled(ateam):
    await sync_to_async(SignalSourceConfig.objects.create)(
        team=ateam,
        source_product=SignalSourceConfig.SourceProduct.LLM_ANALYTICS,
        source_type=SignalSourceConfig.SourceType.EVALUATION,
        enabled=False,
        config={"evaluation_ids": ["eval-123"]},
    )


async def _setup_org_not_ai_approved(ateam):
    org = ateam.organization
    org.is_ai_data_processing_approved = False
    await sync_to_async(org.save)()
    await sync_to_async(SignalSourceConfig.objects.create)(
        team=ateam,
        source_product=SignalSourceConfig.SourceProduct.LLM_ANALYTICS,
        source_type=SignalSourceConfig.SourceType.EVALUATION,
        enabled=True,
        config={"evaluation_ids": ["eval-123"]},
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestEmitEvalReportSignalActivity:
    @pytest.mark.parametrize(
        "setup_fn",
        [
            _setup_no_source_config,
            _setup_evaluation_not_in_allowlist,
            _setup_config_disabled,
            _setup_org_not_ai_approved,
        ],
        ids=["no_source_config", "evaluation_not_in_allowlist", "config_disabled", "org_not_ai_approved"],
    )
    async def test_skips_when_gate_fails(self, ateam, setup_fn):
        await setup_fn(ateam)
        inputs = _make_inputs(team_id=ateam.id, evaluation_id="eval-123")
        with (
            patch(
                "posthog.temporal.llm_analytics.eval_reports.emit_signal.summarize_report_for_signal"
            ) as mock_summarize,
            patch("products.signals.backend.api.emit_signal", new_callable=AsyncMock) as mock_emit,
        ):
            await emit_eval_report_signal_activity(inputs)
        mock_summarize.assert_not_called()
        mock_emit.assert_not_called()

    async def test_emits_signal_when_gates_pass(self, ateam):
        await sync_to_async(SignalSourceConfig.objects.create)(
            team=ateam,
            source_product=SignalSourceConfig.SourceProduct.LLM_ANALYTICS,
            source_type=SignalSourceConfig.SourceType.EVALUATION,
            enabled=True,
            config={"evaluation_ids": ["eval-123"]},
        )
        inputs = _make_inputs(team_id=ateam.id, evaluation_id="eval-123")
        summary = EvalReportSignalSummary(
            title="Pass rate dropped sharply",
            description="Pass rate fell 14pp; failures concentrated on gpt-5-mini.",
            significance=0.75,
        )
        with (
            patch(
                "posthog.temporal.llm_analytics.eval_reports.emit_signal.summarize_report_for_signal",
                new_callable=AsyncMock,
                return_value=summary,
            ),
            patch(
                "posthog.temporal.llm_analytics.eval_reports.emit_signal.EvaluationReportRun.objects.values_list"
            ) as mock_values_list,
            patch("products.signals.backend.api.emit_signal", new_callable=AsyncMock) as mock_emit,
        ):
            mock_values_list.return_value.get.return_value = _make_content()
            await emit_eval_report_signal_activity(inputs)

        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args.kwargs
        assert call_kwargs["source_product"] == "llm_analytics"
        assert call_kwargs["source_type"] == "evaluation_report"
        assert call_kwargs["source_id"] == "eval-123:report:run-xyz"
        assert call_kwargs["weight"] == 0.75
        assert call_kwargs["description"] == summary.description
        extra = call_kwargs["extra"]
        assert extra["evaluation_id"] == "eval-123"
        assert extra["evaluation_name"] == "Cost cap check"
        assert extra["evaluation_description"] == "Flag generations above the cost cap"
        assert extra["report_id"] == "report-abc"
        assert extra["report_run_id"] == "run-xyz"
        assert extra["period_start"] == inputs.period_start
        assert extra["period_end"] == inputs.period_end

    async def test_emits_even_for_low_significance(self, ateam):
        """No significance threshold — downstream grouping is responsible for filtering noise."""
        await sync_to_async(SignalSourceConfig.objects.create)(
            team=ateam,
            source_product=SignalSourceConfig.SourceProduct.LLM_ANALYTICS,
            source_type=SignalSourceConfig.SourceType.EVALUATION,
            enabled=True,
            config={"evaluation_ids": ["eval-123"]},
        )
        inputs = _make_inputs(team_id=ateam.id, evaluation_id="eval-123")
        summary = EvalReportSignalSummary(
            title="Nothing unusual",
            description="Pass rate held steady at 86%.",
            significance=0.02,
        )
        with (
            patch(
                "posthog.temporal.llm_analytics.eval_reports.emit_signal.summarize_report_for_signal",
                new_callable=AsyncMock,
                return_value=summary,
            ),
            patch(
                "posthog.temporal.llm_analytics.eval_reports.emit_signal.EvaluationReportRun.objects.values_list"
            ) as mock_values_list,
            patch("products.signals.backend.api.emit_signal", new_callable=AsyncMock) as mock_emit,
        ):
            mock_values_list.return_value.get.return_value = _make_content()
            await emit_eval_report_signal_activity(inputs)
        mock_emit.assert_called_once()


class TestEvalReportSignalSchemaContract:
    """Lock the (source_product, source_type) -> variant mapping that emit_signal validates against.

    Mocking emit_signal in activity tests hides schema mismatches — the original review
    cycle caught one only because the bots ran static checks. This exercises the same
    dispatch path emit_signal uses (`_SIGNAL_VARIANT_LOOKUP`) so any drift between the
    schema source and the activity's payload shape will fail in unit tests.
    """

    def test_evaluation_report_variant_is_registered(self):
        from products.signals.backend.api import _SIGNAL_VARIANT_LOOKUP

        variant = _SIGNAL_VARIANT_LOOKUP.get(("llm_analytics", "evaluation_report"))
        assert variant is not None, (
            "No SignalInput variant for (llm_analytics, evaluation_report). "
            "Did the schema source drift? Re-run `pnpm run schema:build`."
        )

    def test_activity_payload_validates_against_variant(self):
        """Construct the exact emit_signal kwargs the activity sends and validate them."""
        from products.signals.backend.api import _SIGNAL_VARIANT_LOOKUP

        variant = _SIGNAL_VARIANT_LOOKUP[("llm_analytics", "evaluation_report")]
        payload = {
            "source_product": "llm_analytics",
            "source_type": "evaluation_report",
            "source_id": "eval-123:report:run-xyz",
            "description": "Pass rate fell 14pp; failures concentrated on gpt-5-mini.",
            "weight": 0.75,
            "extra": {
                "evaluation_id": "eval-123",
                "evaluation_name": "Cost cap check",
                "evaluation_description": "Flag generations above the cost cap",
                "report_id": "report-abc",
                "report_run_id": "run-xyz",
                "period_start": "2026-04-01T00:00:00+00:00",
                "period_end": "2026-04-02T00:00:00+00:00",
            },
        }
        # Will raise ValidationError if the schema source drifts from the activity's
        # payload shape — including extra-key forbidden, missing required keys, or
        # source_type literal mismatch.
        variant.model_validate(payload)
