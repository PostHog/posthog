from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

from products.apm.backend.feature_flags import UNIFIED_APM_PRODUCT_FLAG, is_apm_enabled


class TestApmFeatureFlag(TestCase):
    @parameterized.expand(
        [
            (True, True),
            (False, False),
            (None, False),
        ]
    )
    def test_gate_reflects_flag_state(self, flag_result: bool | None, expected: bool) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=flag_result):
            assert is_apm_enabled(team_id=1) is expected

    def test_gate_stays_closed_when_flag_service_raises(self) -> None:
        with patch("posthoganalytics.feature_enabled", side_effect=RuntimeError("flags unreachable")):
            assert is_apm_enabled(team_id=1) is False

    def test_gate_evaluates_for_the_user_when_one_is_given(self) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=True) as feature_enabled:
            is_apm_enabled(team_id=7, distinct_id="user-distinct-id", email="hog@example.com")

        args, kwargs = feature_enabled.call_args
        assert args == (UNIFIED_APM_PRODUCT_FLAG, "user-distinct-id")
        assert kwargs["person_properties"] == {"email": "hog@example.com"}
        assert kwargs["groups"] == {"project": "7"}

    def test_gate_sends_an_explicit_null_email_for_an_anonymized_user(self) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=True) as feature_enabled:
            is_apm_enabled(team_id=7, distinct_id="user-distinct-id", email=None)

        _, kwargs = feature_enabled.call_args
        assert kwargs["person_properties"] == {"email": None}

    def test_gate_evaluates_for_the_team_when_no_user_is_given(self) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=True) as feature_enabled:
            is_apm_enabled(team_id=7)

        args, kwargs = feature_enabled.call_args
        assert args == (UNIFIED_APM_PRODUCT_FLAG, "7")
        assert not kwargs["person_properties"]
        assert kwargs["groups"] == {"project": "7"}
