"""Tests for the Stage A evaluation sampler activity."""

from contextlib import asynccontextmanager

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.llm_analytics.evaluation_clustering.constants import LLMA_EVALUATION_DOCUMENT_TYPE
from posthog.temporal.llm_analytics.evaluation_clustering.models import SamplerActivityInputs
from posthog.temporal.llm_analytics.evaluation_clustering.sampling import (
    _compose_evaluation_text,
    sample_and_embed_for_job_activity,
)


@asynccontextmanager
async def _noop_heartbeater(*args, **kwargs):
    yield


@pytest.fixture
def mock_team(db):
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    organization = Organization.objects.create(name="Test Org Eval Sampler")
    team = Team.objects.create(organization=organization, name="Eval Sampler Team")
    return team


class TestComposeEvaluationText:
    @parameterized.expand(
        [
            # (name, result, applicable, reasoning, expected_verdict_line)
            ("bool-true-pass", True, None, "looks good", "Verdict: pass"),
            ("bool-false-fail", False, None, "not good", "Verdict: fail"),
            ("string-true-pass", "true", None, "ok", "Verdict: pass"),
            ("string-false-fail", "false", None, "bad", "Verdict: fail"),
            ("applicable-false-overrides", True, False, "doesn't apply", "Verdict: n/a"),
            ("applicable-string-false", True, "false", "na", "Verdict: n/a"),
            ("applicable-true-keeps-verdict", True, True, "applies and passes", "Verdict: pass"),
            ("missing-result-unknown", None, None, "hmm", "Verdict: unknown"),
        ]
    )
    def test_verdict_resolution(self, _name, result, applicable, reasoning, expected_verdict_line):
        text = _compose_evaluation_text(name="MyEval", result=result, applicable=applicable, reasoning=reasoning)
        assert expected_verdict_line in text
        assert "Evaluation: MyEval" in text
        assert f"Reasoning: {reasoning or ''}" in text

    def test_missing_name_and_reasoning_degrade_gracefully(self):
        text = _compose_evaluation_text(name=None, result=True, applicable=None, reasoning=None)
        assert "Evaluation: unknown" in text
        assert "Reasoning: " in text

    def test_description_is_included_when_provided(self):
        text = _compose_evaluation_text(
            name="Relevance",
            result=True,
            applicable=None,
            reasoning="response fit",
            description="Checks that the model's answer is on-topic for the user's question",
        )
        # Description line sits between name and verdict so the verdict/reasoning stay at the end
        assert text.splitlines() == [
            "Evaluation: Relevance",
            "Description: Checks that the model's answer is on-topic for the user's question",
            "Verdict: pass",
            "Reasoning: response fit",
        ]

    # Empty string — treat as absent to avoid flattening the embedding space with boilerplate
    @parameterized.expand(
        [
            ("none_description", None),
            ("empty_description", ""),
        ]
    )
    def test_description_omitted_when_empty_or_none(self, _name, desc):
        text = _compose_evaluation_text(
            name="Relevance", result=True, applicable=None, reasoning="ok", description=desc
        )
        assert "Description:" not in text


@patch(
    "posthog.temporal.llm_analytics.evaluation_clustering.sampling.Heartbeater",
    _noop_heartbeater,
)
class TestSampleAndEmbedForJobActivity:
    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_enqueues_one_embedding_per_row(self, mock_team):
        # Row shape mirrors the HogQL SELECT:
        # [event_uuid, eval_name, eval_result, eval_applicable, eval_reasoning, eval_id]
        rows = [
            ["uuid-1", "Accuracy", True, None, "Response was factually correct", "eval-acc"],
            ["uuid-2", "Accuracy", False, None, "Missed the key detail", "eval-acc"],
            ["uuid-3", "Applicability", True, False, "Out of scope", "eval-app"],
        ]

        inputs = SamplerActivityInputs(
            team_id=mock_team.id,
            job_id="job-abc",
            job_name="Eval Clustering Job",
            run_ts="2026-04-15T12:00:00Z",
            window_start="2026-04-15T10:30:00Z",
            window_end="2026-04-15T11:30:00Z",
            max_samples=250,
            event_filters=[],
        )

        with (
            patch("posthog.temporal.llm_analytics.evaluation_clustering.sampling.execute_hogql_query") as mock_execute,
            patch(
                "posthog.temporal.llm_analytics.evaluation_clustering.sampling.LLMTracesSummarizerEmbedder"
            ) as mock_embedder_cls,
            patch(
                "posthog.temporal.llm_analytics.evaluation_clustering.sampling._fetch_evaluation_descriptions",
                return_value={"eval-acc": "Checks factual correctness of the answer"},
            ),
        ):
            mock_execute.return_value.results = rows
            mock_embedder = MagicMock()
            mock_embedder_cls.return_value = mock_embedder

            result = await sample_and_embed_for_job_activity(inputs)

        assert result.sampled == 3
        assert result.embedded == 3
        assert result.team_id == mock_team.id
        assert result.job_id == "job-abc"

        # Every call used the eval document type and the team-scoped rendering suffix
        expected_rendering = f"{mock_team.id}_2026-04-15T12:00:00Z_job-abc"
        calls = mock_embedder.embed_document.call_args_list
        assert len(calls) == 3
        for call in calls:
            kwargs = call.kwargs
            assert kwargs["document_type"] == LLMA_EVALUATION_DOCUMENT_TYPE
            assert kwargs["rendering"] == expected_rendering
            assert "Evaluation:" in kwargs["content"]

        # Third row's N/A verdict is surfaced in the composed text
        na_content = calls[2].kwargs["content"]
        assert "Verdict: n/a" in na_content

        # Accuracy rows carry the description from the Evaluation model
        assert "Description: Checks factual correctness of the answer" in calls[0].kwargs["content"]
        assert "Description: Checks factual correctness of the answer" in calls[1].kwargs["content"]
        # Applicability has no description — the line stays out of the composed text
        assert "Description:" not in na_content

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_empty_window_returns_zero(self, mock_team):
        inputs = SamplerActivityInputs(
            team_id=mock_team.id,
            job_id="job-abc",
            job_name="",
            run_ts="2026-04-15T12:00:00Z",
            window_start="2026-04-15T10:30:00Z",
            window_end="2026-04-15T11:30:00Z",
            max_samples=250,
            event_filters=[],
        )

        with (
            patch("posthog.temporal.llm_analytics.evaluation_clustering.sampling.execute_hogql_query") as mock_execute,
            patch(
                "posthog.temporal.llm_analytics.evaluation_clustering.sampling.LLMTracesSummarizerEmbedder"
            ) as mock_embedder_cls,
        ):
            mock_execute.return_value.results = []
            mock_embedder = MagicMock()
            mock_embedder_cls.return_value = mock_embedder

            result = await sample_and_embed_for_job_activity(inputs)

        assert result.sampled == 0
        assert result.embedded == 0
        mock_embedder.embed_document.assert_not_called()

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_event_filter_propagated_to_query(self, mock_team):
        inputs = SamplerActivityInputs(
            team_id=mock_team.id,
            job_id="job-abc",
            job_name="",
            run_ts="2026-04-15T12:00:00Z",
            window_start="2026-04-15T10:30:00Z",
            window_end="2026-04-15T11:30:00Z",
            max_samples=250,
            event_filters=[
                {
                    "key": "$ai_evaluation_name",
                    "value": ["Accuracy"],
                    "operator": "exact",
                    "type": "event",
                }
            ],
        )

        with (
            patch("posthog.temporal.llm_analytics.evaluation_clustering.sampling.execute_hogql_query") as mock_execute,
            patch("posthog.temporal.llm_analytics.evaluation_clustering.sampling.LLMTracesSummarizerEmbedder"),
        ):
            mock_execute.return_value.results = []
            await sample_and_embed_for_job_activity(inputs)

            placeholders = mock_execute.call_args.kwargs["placeholders"]
            # filter_expr is a real HogQL expr (not the pass-through True literal) when filters are provided
            filter_expr = placeholders["filter_expr"]
            assert filter_expr.__class__.__name__ != "Constant"
