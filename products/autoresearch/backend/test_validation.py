from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.autoresearch.backend.validation import _run_validation, validate_pipeline_definition


def _make_mock_runner(positives: int, total: int):
    mock_result = MagicMock()
    mock_result.results = [[positives, total]]
    mock_runner = MagicMock()
    mock_runner.run.return_value = mock_result
    return mock_runner


class TestValidationWarnings(BaseTest):
    def setUp(self):
        super().setUp()

    def _run(self, positives: int, total: int, prediction_mode: str = "adoption", horizon_days: int = 7):
        with patch("products.autoresearch.backend.validation.HogQLQueryRunner") as mock_cls:
            mock_cls.return_value = _make_mock_runner(positives, total)
            return _run_validation(
                team=self.team,
                target_event="$pageview",
                horizon_days=horizon_days,
                prediction_mode=prediction_mode,
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

    def test_adoption_high_base_rate_warning(self):
        result = self._run(positives=700, total=1000, prediction_mode="adoption")
        codes = [w.code for w in result.warnings]
        assert "adoption_high_base_rate" in codes

    def test_continuation_low_base_rate_warning(self):
        result = self._run(positives=50, total=1000, prediction_mode="continuation")
        codes = [w.code for w in result.warnings]
        assert "continuation_low_base_rate" in codes

    def test_error_in_query_returns_error_result(self):
        with patch("products.autoresearch.backend.validation.HogQLQueryRunner") as mock_cls:
            mock_cls.return_value.run.side_effect = RuntimeError("CH is down")
            result = validate_pipeline_definition(
                team=self.team,
                target_event="$pageview",
                horizon_days=7,
                prediction_mode="adoption",
                training_population={},
                inference_population={},
            )
        assert result.can_proceed is False
        assert result.error is not None
        assert "CH is down" in result.error

    def test_zero_users_returns_low_volume_error(self):
        result = self._run(positives=0, total=0)
        assert result.can_proceed is False
        codes = [w.code for w in result.warnings]
        assert "low_volume" in codes
