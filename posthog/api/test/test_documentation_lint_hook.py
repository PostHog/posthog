"""Tests for posthog.api.documentation.lint_spec_consistency_hook."""

import pytest
from unittest.mock import patch

from posthog.api.documentation import lint_spec_consistency_hook


@pytest.mark.parametrize(
    "operation_id,should_warn",
    [
        ("llm_analytics_personal_spend_list", False),
        ("clean_snake_case_id", False),
        ("CamelCaseId", False),
        ("_underscore_prefix", False),
        ("llm_analytics_@me_spend_list", True),
        ("path-with-dashes", True),
        ("contains.dots", True),
        ("trailing space ", True),
        ("123_starts_with_digit", True),
    ],
)
def test_lint_spec_consistency_hook_operation_id_validation(operation_id: str, should_warn: bool) -> None:
    spec = {
        "paths": {
            "/api/test/": {
                "get": {"operationId": operation_id},
            },
        },
    }
    with patch("posthog.api.documentation.spectacular_warn") as mock_warn:
        lint_spec_consistency_hook(spec, generator=None, request=None, public=True)
        warned_about_op_id = any(
            "operationId" in str(call_args.args[0]) and operation_id in str(call_args.args[0])
            for call_args in mock_warn.call_args_list
        )
        assert warned_about_op_id is should_warn, (
            f"operationId {operation_id!r} expected should_warn={should_warn} but got {warned_about_op_id}. "
            f"All warnings: {[c.args[0] for c in mock_warn.call_args_list]}"
        )


def test_lint_spec_consistency_hook_skips_non_method_keys() -> None:
    """`parameters`, `summary`, etc. on a path object aren't HTTP methods — skip them."""
    spec = {
        "paths": {
            "/api/test/": {
                "parameters": [{"name": "weird-name"}],
                "get": {"operationId": "valid_id"},
            },
        },
    }
    with patch("posthog.api.documentation.spectacular_warn") as mock_warn:
        lint_spec_consistency_hook(spec, generator=None, request=None, public=True)
        op_id_warnings = [c for c in mock_warn.call_args_list if "operationId" in str(c.args[0])]
        assert op_id_warnings == []
