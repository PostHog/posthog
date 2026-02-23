import unittest

from parameterized import parameterized

from products.browser_lab_testing.backend.temporal.run_browser_lab_test.activities import (
    _resolve_placeholders,
    _resolve_step,
)


class TestResolvePlaceholders(unittest.TestCase):
    @parameterized.expand(
        [
            ("single", "{{secrets.PASSWORD}}", {"PASSWORD": "hunter2"}, "hunter2"),
            (
                "multiple",
                "{{secrets.USER}}:{{secrets.PASS}}",
                {"USER": "admin", "PASS": "secret"},
                "admin:secret",
            ),
            ("missing_key", "{{secrets.MISSING}}", {}, "{{secrets.MISSING}}"),
            ("no_placeholders", "plain text", {"KEY": "val"}, "plain text"),
            (
                "embedded_in_url",
                "https://example.com?token={{secrets.TOKEN}}",
                {"TOKEN": "abc123"},
                "https://example.com?token=abc123",
            ),
            ("empty_secrets", "{{secrets.X}}", {}, "{{secrets.X}}"),
        ],
    )
    def test_resolve_placeholders(self, _name: str, value: str, secrets: dict, expected: str):
        assert _resolve_placeholders(value, secrets) == expected


class TestResolveStep(unittest.TestCase):
    @parameterized.expand(
        [
            (
                "resolves_strings",
                {"action": "type", "selector": "#pw", "text": "{{secrets.PASS}}"},
                {"PASS": "hunter2"},
                {"action": "type", "selector": "#pw", "text": "hunter2"},
            ),
            (
                "leaves_non_strings",
                {"action": "wait", "timeout": 5000, "text": "{{secrets.X}}"},
                {"X": "val"},
                {"action": "wait", "timeout": 5000, "text": "val"},
            ),
        ],
    )
    def test_resolve_step(self, _name: str, step: dict, secrets: dict, expected: dict):
        assert _resolve_step(step, secrets) == expected
