from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.autoresearch.backend.dataset.validation import _run_validation, validate_pipeline_definition


def _mock_rows(positives: int, total: int, identified: int | None = None) -> list[list[list[int]]]:
    """
    Validation issues three HogQL queries in order:
      1. eligible count            -> [[eligible_identified, eligible_all]]
      2. random-T0 sampled labeler -> [[sampled_users, sampled_positives]]
      3. inference population count -> [[inference_size]]
    The inference count runs whenever an inference filter applies, including the v1
    identified-only restriction, which is always on. For tests we assume sample size
    == total (i.e. total <= live sample cap) so the extrapolated positives line up with
    the input. `identified` defaults to `total` (no anonymous remainder, so no
    mostly-anonymous warning).
    """
    eligible_identified = total if identified is None else identified
    return [
        [[eligible_identified, total]],
        [[eligible_identified, positives]],
        [[eligible_identified]],
    ]


class TestValidationWarnings(BaseTest):
    def setUp(self):
        super().setUp()

    def _run(
        self,
        positives: int,
        total: int,
        horizon_days: int = 7,
        training_lookback_days: int = 180,
        identified: int | None = None,
    ):
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

    def test_ok_result_has_no_warnings(self):
        result = self._run(positives=100, total=1000)
        assert result.can_proceed is True
        assert result.requires_acknowledgement is False
        assert result.warnings == []
        assert result.base_rate == 0.1

    def test_low_volume_is_error(self):
        result = self._run(positives=10, total=50)
        codes = [w.code for w in result.warnings]
        assert "low_volume" in codes
        assert result.can_proceed is False

    def test_moderate_volume_is_warning(self):
        result = self._run(positives=30, total=200)
        codes = [w.code for w in result.warnings]
        assert "moderate_volume" in codes
        assert result.can_proceed is True
        assert result.requires_acknowledgement is True

    def test_low_positives_is_error(self):
        result = self._run(positives=5, total=1000)
        codes = [w.code for w in result.warnings]
        assert "low_positives" in codes
        assert result.can_proceed is False

    def test_extreme_imbalance_is_warning(self):
        result = self._run(positives=1, total=10000)
        codes = [w.code for w in result.warnings]
        assert "extreme_imbalance" in codes

    def test_near_universal_is_warning(self):
        result = self._run(positives=980, total=1000)
        codes = [w.code for w in result.warnings]
        assert "near_universal" in codes

    def test_mostly_anonymous_population_is_warning(self):
        result = self._run(positives=40, total=1000, identified=200)
        codes = [w.code for w in result.warnings]
        assert "mostly_anonymous_population" in codes
        assert result.can_proceed is True
        assert result.estimated_training_rows == 200

    def test_majority_identified_population_has_no_anonymous_warning(self):
        result = self._run(positives=100, total=1000, identified=900)
        codes = [w.code for w in result.warnings]
        assert "mostly_anonymous_population" not in codes

    def test_error_in_query_returns_error_result(self):
        with patch("products.autoresearch.backend.dataset.validation.run_hogql_rows") as mock_run:
            mock_run.side_effect = RuntimeError("CH is down")
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
        assert "CH is down" in result.error

    @parameterized.expand([("short_horizon_floors_at_30", 7, 30), ("long_horizon_is_4x", 14, 56)])
    def test_inference_preview_uses_scoring_lookback(self, _name, horizon_days, expected_lookback):
        # Scoring anchors on max(30, 4 * horizon); previewing over the 180-day training
        # lookback overstates the population that will actually be scored.
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

    def test_zero_users_returns_low_volume_error(self):
        result = self._run(positives=0, total=0)
        assert result.can_proceed is False
        codes = [w.code for w in result.warnings]
        assert "low_volume" in codes
