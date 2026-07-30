import pytest
from unittest.mock import patch

from products.apm.backend.feature_flags import is_apm_enabled


@pytest.mark.parametrize(
    "flag_result,expected",
    [
        (True, True),
        (False, False),
        (None, False),
    ],
)
def test_gate_reflects_flag_state(flag_result: bool | None, expected: bool) -> None:
    with patch("posthoganalytics.feature_enabled", return_value=flag_result):
        assert is_apm_enabled(team_id=1) is expected


def test_gate_stays_closed_when_flag_service_raises() -> None:
    with patch("posthoganalytics.feature_enabled", side_effect=RuntimeError("flags unreachable")):
        assert is_apm_enabled(team_id=1) is False
