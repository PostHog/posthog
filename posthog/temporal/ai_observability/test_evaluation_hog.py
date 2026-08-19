import json

import pytest

from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.temporal.ai_observability.evaluation_errors import is_terminal_user_error_result
from posthog.temporal.ai_observability.evaluation_hog import execute_hog_eval_bytecode, finalize_hog_eval_result

from products.ai_observability.backend.hog import compile_ai_observability_hog

# The failure shape these tests exercise: an operator applied to a property the source assumes is a
# string, against an event where the same property arrived as some other type.
ILIKE_SOURCE = """
if (properties['$ai_output'] ilike '%truncated%') {
    return false
}
return true
"""

JSON_PARSE_SOURCE = """
return jsonParse(properties['$ai_output']) == null
"""

NON_BOOLEAN_SOURCE = """
return 42
"""

# Nothing validates builtin arity at save time, so this compiles and raises IndexError in the STL.
MISSING_ARGUMENT_SOURCE = """
return jsonParse()
"""

EVALUATION = {"id": "01890000-0000-0000-0000-000000000000", "team_id": 1}


def run_source(source: str, property_value: object = "", *, allows_na: bool = True) -> dict:
    bytecode = compile_ai_observability_hog(source, "destination")
    return execute_hog_eval_bytecode(bytecode, {"properties": {"$ai_output": property_value}}, allows_na=allows_na)


class TestHogInputErrorClassification:
    @parameterized.expand(
        [
            ("list_against_ilike", ILIKE_SOURCE, ["stop"]),
            ("dict_against_ilike", ILIKE_SOURCE, {"reason": "stop"}),
            ("int_against_ilike", ILIKE_SOURCE, 7),
            ("truncated_json_against_json_parse", JSON_PARSE_SOURCE, '{"ok": tr'),
        ]
    )
    def test_unsupported_property_type_is_an_input_error(self, _name: str, source: str, property_value: object) -> None:
        result = run_source(source, property_value)

        assert result["user_input_error"] is True
        assert "unexpected" not in result

    def test_supported_property_type_still_evaluates(self) -> None:
        result = run_source(ILIKE_SOURCE, json.dumps(["truncated"]))

        assert result["error"] is None
        assert result["verdict"] is False

    # The exclusions from HOG_INPUT_ERROR_TYPES are invisible otherwise: widening the tuple back to
    # Exception leaves every case above classifying identically, so only a case that must NOT be an
    # input error can catch it. A source that fails on every unit has to stay loud, or it skips
    # forever while blaming the customer's data.
    def test_source_that_can_never_run_stays_our_bug(self) -> None:
        result = run_source(MISSING_ARGUMENT_SOURCE)

        assert result["unexpected"] is True
        assert "user_input_error" not in result


class TestFinalizeHogEvalResult:
    @parameterized.expand([("allows_na", True, None), ("disallows_na", False, False)])
    def test_input_error_skips_the_unit_without_disabling_the_evaluation(
        self, _name: str, allows_na: bool, expected_verdict: bool | None
    ) -> None:
        result = finalize_hog_eval_result(
            run_source(ILIKE_SOURCE, ["stop"], allows_na=allows_na),
            evaluation=EVALUATION,
            allows_na=allows_na,
            unit_label=None,
        )

        assert result["skipped"] is True
        assert result["skip_reason"] == "hog_input_error"
        assert result["verdict"] == expected_verdict
        # Both absent is what keeps the workflow from calling disable_evaluation_activity, so the
        # evaluation survives one unreadable unit and keeps scoring later ones.
        assert is_terminal_user_error_result(result) is False
        assert "status_reason" not in result

    def test_input_error_reasoning_leads_with_the_readable_message(self) -> None:
        result = finalize_hog_eval_result(
            run_source(ILIKE_SOURCE, ["stop"]),
            evaluation=EVALUATION,
            allows_na=True,
            unit_label=None,
        )

        # `reasoning` is the only text the run shows the user, and a bare Python exception repr is
        # not a Hog concept, so the readable sentence has to come first.
        assert result["reasoning"].startswith("The evaluation code could not handle the data for this run")
        assert "TypeError" in result["reasoning"]

    def test_broken_hog_source_still_disables_the_evaluation(self) -> None:
        result = finalize_hog_eval_result(
            run_source(NON_BOOLEAN_SOURCE, allows_na=False),
            evaluation=EVALUATION,
            allows_na=False,
            unit_label=None,
        )

        assert result["skip_reason"] == "hog_error"
        assert is_terminal_user_error_result(result) is True

    @parameterized.expand([("generation", None, r"Hog evaluation error:"), ("trace", "trace", r"error \(trace\):")])
    def test_our_own_bug_still_raises(self, _name: str, unit_label: str | None, expected: str) -> None:
        with pytest.raises(ApplicationError, match=expected):
            finalize_hog_eval_result(
                {"verdict": None, "reasoning": "", "error": "RuntimeError: boom", "unexpected": True},
                evaluation=EVALUATION,
                allows_na=False,
                unit_label=unit_label,
            )
