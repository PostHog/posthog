from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql.errors import QueryError

from products.autoresearch.backend.dataset.labeling import LABELER_QUERY_MODIFIERS, PREDICTION_EVENT_NAME
from products.autoresearch.backend.dataset.validation import (
    ValidationResult,
    _run_validation,
    validate_pipeline_definition,
)


def _mock_rows(positives: int, total: int, identified: int | None = None) -> list[list[list[int]]]:
    # Query order: eligible count, sampled labeler, inference count. Sample size
    # equals total so the extrapolated positives line up with the input.
    eligible_identified = total if identified is None else identified
    return [
        [[eligible_identified, total]],
        [[eligible_identified, positives]],
        [[eligible_identified]],
    ]


class TestValidationWarnings(BaseTest):
    def _run(
        self,
        positives: int,
        total: int,
        horizon_days: int = 7,
        training_lookback_days: int = 180,
        identified: int | None = None,
    ) -> ValidationResult:
        with patch("products.autoresearch.backend.dataset.validation.run_hogql_rows") as mock_run:
            mock_run.side_effect = _mock_rows(positives, total, identified=identified)
            return _run_validation(
                team=self.team,
                target_event="$pageview",
                horizon_days=horizon_days,
                training_lookback_days=training_lookback_days,
                training_population={},
                inference_population={},
            )

    def test_ok_result_has_no_warnings(self) -> None:
        result = self._run(positives=100, total=1000)
        assert result.can_proceed is True
        assert result.requires_acknowledgement is False
        assert result.warnings == []
        assert result.base_rate == 0.1

    @parameterized.expand(
        [
            ("low_volume", 10, 50, "low_volume"),
            ("zero_users", 0, 0, "low_volume"),
            ("low_positives", 5, 1000, "low_positives"),
            ("low_negatives", 995, 1000, "low_negatives"),
            ("population_too_large", 5_000, 50_000, "population_too_large"),
        ]
    )
    def test_hard_errors_block_proceeding(self, _name: str, positives: int, total: int, code: str) -> None:
        result = self._run(positives=positives, total=total)
        codes = [w.code for w in result.warnings]
        assert code in codes
        assert result.can_proceed is False

    def test_moderate_volume_is_warning(self) -> None:
        result = self._run(positives=30, total=200)
        codes = [w.code for w in result.warnings]
        assert "moderate_volume" in codes
        assert result.can_proceed is True
        assert result.requires_acknowledgement is True

    def test_extreme_imbalance_is_warning(self) -> None:
        result = self._run(positives=1, total=10000)
        codes = [w.code for w in result.warnings]
        assert "extreme_imbalance" in codes

    def test_near_universal_is_warning(self) -> None:
        result = self._run(positives=970, total=1000)
        codes = [w.code for w in result.warnings]
        assert "near_universal" in codes
        assert result.can_proceed is True

    def test_mostly_anonymous_population_is_warning(self) -> None:
        result = self._run(positives=40, total=1000, identified=200)
        codes = [w.code for w in result.warnings]
        assert "mostly_anonymous_population" in codes
        assert result.can_proceed is True
        assert result.estimated_training_rows == 200

    def test_majority_identified_population_has_no_anonymous_warning(self) -> None:
        result = self._run(positives=100, total=1000, identified=900)
        codes = [w.code for w in result.warnings]
        assert "mostly_anonymous_population" not in codes

    @parameterized.expand(
        [
            (
                "infrastructure_detail_stays_in_the_log",
                RuntimeError("CH is down at 10.0.0.1"),
                "Validation could not run",
            ),
            ("query_error_reaches_the_caller", QueryError("Field not found: nope"), "Field not found: nope"),
        ]
    )
    def test_error_in_query_returns_error_result(self, _name: str, exc: Exception, expected: str) -> None:
        with patch("products.autoresearch.backend.dataset.validation.run_hogql_rows") as mock_run:
            mock_run.side_effect = exc
            result = validate_pipeline_definition(
                team=self.team,
                target_event="$pageview",
                horizon_days=7,
                training_lookback_days=180,
                training_population={},
                inference_population={},
            )
        assert result.can_proceed is False
        assert result.error is not None
        assert expected in result.error
        assert "10.0.0.1" not in result.error

    def test_horizon_at_or_past_the_lookback_is_refused_before_any_query(self) -> None:
        with patch("products.autoresearch.backend.dataset.validation.run_hogql_rows") as mock_run:
            result = _run_validation(
                team=self.team,
                target_event="$pageview",
                horizon_days=180,
                training_lookback_days=180,
                training_population={},
                inference_population={},
            )
        assert mock_run.call_count == 0
        assert result.can_proceed is False
        assert [w.code for w in result.warnings] == ["horizon_exceeds_lookback"]

    def test_count_queries_use_the_labeler_join_mode_and_skip_own_events(self) -> None:
        with patch("products.autoresearch.backend.dataset.validation.run_hogql_rows") as mock_run:
            mock_run.side_effect = _mock_rows(100, 1000)
            _run_validation(
                team=self.team,
                target_event="$pageview",
                horizon_days=7,
                training_lookback_days=180,
                training_population={},
                inference_population={},
            )
        queries = [call.kwargs["query"] for call in mock_run.call_args_list]
        assert [q.modifiers for q in queries] == [LABELER_QUERY_MODIFIERS] * 3
        assert all(f"event != '{PREDICTION_EVENT_NAME}'" in q.query for q in queries)

    @parameterized.expand([("short_horizon_floors_at_30", 7, 30), ("long_horizon_is_4x", 14, 56)])
    def test_inference_preview_matches_the_scoring_window(
        self, _name: str, horizon_days: int, expected_lookback: int
    ) -> None:
        # Scoring anchors on max(30, 4 * horizon) at the UTC midnight of the prediction date;
        # previewing over the training lookback at now() would count a different population.
        with patch("products.autoresearch.backend.dataset.validation.run_hogql_rows") as mock_run:
            mock_run.side_effect = _mock_rows(100, 1000)
            _run_validation(
                team=self.team,
                target_event="$pageview",
                horizon_days=horizon_days,
                training_lookback_days=180,
                training_population={},
                inference_population={},
            )
        inference_query = mock_run.call_args_list[2].kwargs["query"]
        assert inference_query.values["lookback"] == expected_lookback
        assert inference_query.values["cutoff_ts"] % 86400 == 0

    def test_training_window_is_the_configured_lookback(self) -> None:
        with patch("products.autoresearch.backend.dataset.validation.run_hogql_rows") as mock_run:
            mock_run.side_effect = _mock_rows(100, 1000)
            _run_validation(
                team=self.team,
                target_event="$pageview",
                horizon_days=1,
                training_lookback_days=2,
                training_population={},
                inference_population={},
            )
        eligible_query = mock_run.call_args_list[0].kwargs["query"]
        labeler_query = mock_run.call_args_list[1].kwargs["query"]
        assert eligible_query.values["lookback"] == 2
        assert labeler_query.values["lookback"] == 2

    def test_every_count_runs_as_the_given_user(self) -> None:
        with patch("products.autoresearch.backend.dataset.validation.run_hogql_rows") as mock_run:
            mock_run.side_effect = _mock_rows(100, 1000)
            validate_pipeline_definition(
                team=self.team,
                target_event="$pageview",
                horizon_days=7,
                training_lookback_days=180,
                training_population={},
                inference_population={},
                user=self.user,
            )
        assert len(mock_run.call_args_list) == 3
        assert all(call.kwargs["user"] is self.user for call in mock_run.call_args_list)
