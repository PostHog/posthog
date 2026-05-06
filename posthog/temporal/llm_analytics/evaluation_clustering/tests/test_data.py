"""Tests for Stage B data access — embeddings fetch + eval→generation metadata join."""

from datetime import UTC

import pytest
from unittest.mock import patch

from posthog.temporal.llm_analytics.evaluation_clustering.constants import (
    LLMA_EVALUATION_DOCUMENT_TYPE,
    LLMA_EVALUATION_EMBEDDING_MODEL,
)
from posthog.temporal.llm_analytics.evaluation_clustering.data import (
    _coerce_bool,
    fetch_evaluation_embeddings,
    fetch_evaluation_metadata,
)


@pytest.fixture
def mock_team(db):
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    org = Organization.objects.create(name="Eval Data Test Org")
    return Team.objects.create(organization=org, name="Eval Data Test Team")


class TestCoerceBool:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (True, True),
            (False, False),
            ("true", True),
            ("True", True),
            ("false", False),
            ("False", False),
            (None, None),
            ("", None),
            ("maybe", None),
            (1, None),  # not in our contract; ClickHouse returns True/False or strings
        ],
    )
    def test_variants(self, value, expected):
        assert _coerce_bool(value) is expected


class TestFetchEvaluationEmbeddings:
    @pytest.mark.django_db(transaction=True)
    def test_filters_by_doc_type_and_job_suffix(self, mock_team):
        with patch("posthog.temporal.llm_analytics.evaluation_clustering.data.execute_hogql_query") as mock_execute:
            mock_execute.return_value.results = [
                ["uuid-1", [0.1, 0.2, 0.3]],
                ["uuid-2", [0.4, 0.5, 0.6]],
            ]

            eval_ids, embeddings = fetch_evaluation_embeddings(
                team=mock_team,
                job_id="job-abc",
                max_samples=100,
            )

            assert eval_ids == ["uuid-1", "uuid-2"]
            assert embeddings["uuid-1"] == [0.1, 0.2, 0.3]

            placeholders = mock_execute.call_args.kwargs["placeholders"]
            assert placeholders["document_type"].value == LLMA_EVALUATION_DOCUMENT_TYPE
            assert placeholders["model_name"].value == LLMA_EVALUATION_EMBEDDING_MODEL
            assert placeholders["job_id_suffix"].value == "_job-abc"
            assert placeholders["max_samples"].value == 100

    @pytest.mark.django_db(transaction=True)
    def test_empty_results(self, mock_team):
        with patch("posthog.temporal.llm_analytics.evaluation_clustering.data.execute_hogql_query") as mock_execute:
            mock_execute.return_value.results = []
            eval_ids, embeddings = fetch_evaluation_embeddings(team=mock_team, job_id="job-xyz", max_samples=100)
            assert eval_ids == []
            assert embeddings == {}


class TestFetchEvaluationMetadata:
    @pytest.mark.django_db(transaction=True)
    def test_empty_input_returns_empty(self, mock_team):
        from datetime import datetime

        result = fetch_evaluation_metadata(
            team=mock_team,
            eval_event_ids=[],
            window_start=datetime(2026, 4, 15, tzinfo=UTC),
            window_end=datetime(2026, 4, 16, tzinfo=UTC),
        )
        assert result == {}

    @pytest.mark.django_db(transaction=True)
    def test_populates_all_fields_when_generation_present(self, mock_team):
        """Two-query metadata fetch: eval rows, then a second query for linked generations."""
        from datetime import datetime

        # Row shape mirrors _fetch_evaluation_rows SELECT:
        # [event_uuid, eval_id, name, result, applicable, runtime, reasoning, judge_cost, target_gen, target_trace]
        eval_row = [
            "eval-1",
            "cfg-accuracy",
            "Accuracy",
            "true",  # ClickHouse bool properties come back as strings
            None,  # applicable not set
            "llm_judge",
            "The answer was correct.",
            0.0012,
            "gen-1",
            "trace-1",
        ]
        # Row shape mirrors _fetch_linked_generations SELECT
        gen_row = ["gen-1", 0.035, 450.0, 500, 150, "gpt-4o", "false"]

        with patch("posthog.temporal.llm_analytics.evaluation_clustering.data.execute_hogql_query") as mock_execute:
            # First call returns eval rows, second call returns linked generations
            mock_execute.side_effect = [
                type("R", (), {"results": [eval_row]})(),
                type("R", (), {"results": [gen_row]})(),
            ]

            result = fetch_evaluation_metadata(
                team=mock_team,
                eval_event_ids=["eval-1"],
                window_start=datetime(2026, 4, 15, tzinfo=UTC),
                window_end=datetime(2026, 4, 16, tzinfo=UTC),
            )

            assert "eval-1" in result
            meta = result["eval-1"]
            assert meta.evaluation_name == "Accuracy"
            assert meta.evaluation_result is True
            assert meta.evaluation_applicable is None
            assert meta.evaluation_runtime == "llm_judge"
            assert meta.judge_cost_usd == 0.0012
            assert meta.target_generation_id == "gen-1"
            assert meta.target_trace_id == "trace-1"
            assert meta.generation_cost_usd == 0.035
            assert meta.generation_latency_ms == 450.0
            assert meta.generation_model == "gpt-4o"
            assert meta.generation_is_error is False

    @pytest.mark.django_db(transaction=True)
    def test_degrades_when_linked_generation_missing(self, mock_team):
        """Missing generation (second query returns no rows) → None operational fields."""
        from datetime import datetime

        eval_row = [
            "eval-1",
            "cfg-accuracy",
            "Accuracy",
            "false",
            None,
            "llm_judge",
            "Hallucinated the citation.",
            0.0012,
            "gen-1",
            "trace-1",
        ]
        with patch("posthog.temporal.llm_analytics.evaluation_clustering.data.execute_hogql_query") as mock_execute:
            # Eval query returns a row, generation query returns nothing (purged)
            mock_execute.side_effect = [
                type("R", (), {"results": [eval_row]})(),
                type("R", (), {"results": []})(),
            ]
            result = fetch_evaluation_metadata(
                team=mock_team,
                eval_event_ids=["eval-1"],
                window_start=datetime(2026, 4, 15, tzinfo=UTC),
                window_end=datetime(2026, 4, 16, tzinfo=UTC),
            )

            meta = result["eval-1"]
            assert meta.evaluation_result is False  # eval side still populated
            assert meta.generation_cost_usd is None
            assert meta.generation_latency_ms is None
            assert meta.generation_model is None
            assert meta.generation_is_error is None
