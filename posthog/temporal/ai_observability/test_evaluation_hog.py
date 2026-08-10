import json

import pytest

from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.temporal.ai_observability.evaluation_errors import is_terminal_user_error_result
from posthog.temporal.ai_observability.evaluation_hog import execute_hog_eval_bytecode, finalize_hog_eval_result

from products.ai_observability.backend.hog import compile_ai_observability_hog

# The failure shape these tests exercise: a string operator applied to a property the source
# assumes is a string, against an event where the same property arrived as some other type.
STOP_REASON_SOURCE = """
if (properties['$ai_stop_reason'] ilike '%truncated%') {
    return false
}
return true
"""


class TestHogInputErrorClassification:
    @parameterized.expand(
        [
            ("list_against_ilike", ["stop"]),
            ("dict_against_ilike", {"reason": "stop"}),
            ("int_against_ilike", 7),
        ]
    )
    def test_unsupported_property_type_is_an_input_error(self, _name: str, property_value: object) -> None:
        bytecode = compile_ai_observability_hog(STOP_REASON_SOURCE, "destination")

        result = execute_hog_eval_bytecode(
            bytecode,
            {"properties": {"$ai_stop_reason": property_value}},
            allows_na=True,
        )

        assert result["user_input_error"] is True
        assert "unexpected" not in result

    def test_supported_property_type_still_evaluates(self) -> None:
        bytecode = compile_ai_observability_hog(STOP_REASON_SOURCE, "destination")

        result = execute_hog_eval_bytecode(
            bytecode,
            {"properties": {"$ai_stop_reason": json.dumps(["truncated"])}},
            allows_na=True,
        )

        assert result["error"] is None
        assert result["verdict"] is False


class TestFinalizeHogEvalResult:
    @parameterized.expand([("allows_na", True, None), ("disallows_na", False, False)])
    def test_input_error_skips_the_unit_without_disabling_the_evaluation(
        self, _name: str, allows_na: bool, expected_verdict: bool | None
    ) -> None:
        result = finalize_hog_eval_result(
            {
                "verdict": None,
                "reasoning": "",
                "error": "Could not read this event's data: KeyError: 0",
                "user_input_error": True,
            },
            allows_na=allows_na,
        )

        assert result["skipped"] is True
        assert result["skip_reason"] == "hog_input_error"
        assert result["verdict"] == expected_verdict
        # Both absent is what keeps the workflow from calling disable_evaluation_activity, so the
        # evaluation survives one unreadable event and keeps scoring later ones.
        assert is_terminal_user_error_result(result) is False
        assert "status_reason" not in result

    def test_broken_hog_source_still_disables_the_evaluation(self) -> None:
        result = finalize_hog_eval_result(
            {"verdict": None, "reasoning": "", "error": "Must return boolean, got int: 42"},
            allows_na=False,
        )

        assert result["skip_reason"] == "hog_error"
        assert is_terminal_user_error_result(result) is True

    @parameterized.expand([("generation", None, r"Hog evaluation error:"), ("trace", "trace", r"error \(trace\):")])
    def test_our_own_bug_still_raises(self, _name: str, unit_label: str | None, expected: str) -> None:
        with pytest.raises(ApplicationError, match=expected):
            finalize_hog_eval_result(
                {"verdict": None, "reasoning": "", "error": "RuntimeError: boom", "unexpected": True},
                allows_na=False,
                unit_label=unit_label,
            )
