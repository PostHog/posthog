from __future__ import annotations

import unittest

from parameterized import parameterized

from ..logic.janitor_client import JanitorClientError
from ..presentation.views import JanitorUpstreamError


class TestJanitorUpstreamError(unittest.TestCase):
    @parameterized.expand(
        [
            (
                "compile_errors_surfaced",
                422,
                {
                    "error": "tool_compile_failed",
                    "tool_id": "greet",
                    "errors": [
                        {"kind": "ast_missing_actions", "message": "missing required `actions` property", "line": 3}
                    ],
                },
                ["tool_compile_failed", "ast_missing_actions", "missing required `actions`", "(line 3)"],
            ),
            (
                "multiple_errors_joined",
                422,
                {
                    "error": "tool_compile_failed",
                    "errors": [
                        {"kind": "parse_failed", "message": "first"},
                        {"kind": "transform_failed", "message": "second"},
                    ],
                },
                ["parse_failed: first", "transform_failed: second", ";"],
            ),
            (
                "plain_code_when_no_errors",
                404,
                {"error": "not_found"},
                ["not_found"],
            ),
            (
                "json_dump_when_no_known_field",
                502,
                {"unexpected": "shape"},
                ["unexpected", "shape"],
            ),
        ]
    )
    def test_detail(self, _name, status_code, body, expected_substrings):
        exc = JanitorUpstreamError(JanitorClientError(status_code, f"janitor returned {status_code}", body=body))
        self.assertEqual(exc.status_code, status_code)
        detail = str(exc.detail)
        for sub in expected_substrings:
            self.assertIn(sub, detail)
