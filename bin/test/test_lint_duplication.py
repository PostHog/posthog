#!/usr/bin/env python3

import unittest

from parameterized import parameterized

from bin.lint_duplication import (
    APP_MAX_NEW_CLONE_TOKENS,
    TEST_MAX_NEW_CLONE_TOKENS,
    build_findings,
    clone_language,
    find_gate_failures,
    is_test_file,
)


def make_clone(first: str, second: str, tokens: int, is_new: bool = True, fmt: str = "python") -> dict:
    return {
        "firstFile": {"name": first, "start": 1, "end": 10},
        "secondFile": {"name": second, "start": 1, "end": 10},
        "tokens": tokens,
        "lines": 10,
        "isNew": is_new,
        "format": fmt,
    }


class TestIsTestFile(unittest.TestCase):
    @parameterized.expand(
        [
            ("test_prefix", "posthog/api/test/test_team.py", True),
            ("tests_dir", "products/alerts/backend/tests/api/test_alert.py", True),
            ("test_suffix", "posthog/hogql/parser_python_test.py", True),
            ("conftest", "posthog/conftest.py", True),
            ("repo_test_utils", "posthog/test/utils.py", True),
            ("app_viewset", "posthog/api/team.py", False),
            ("testy_is_not_a_test_prefix", "posthog/testimony.py", False),
            ("jest_test_ts", "frontend/src/exporter/Exporter.test.ts", True),
            ("jest_test_tsx", "frontend/src/exporter/ExportedInsight/ExportedInsight.test.tsx", True),
            ("playwright_spec", "playwright/e2e/insight-sharing-password.spec.ts", True),
            ("storybook_story", "frontend/src/scenes/insights/Insight.stories.tsx", True),
            ("tests_underscore_dir", "frontend/src/__tests__/utils.ts", True),
            ("mocks_dir", "frontend/src/__mocks__/server.ts", True),
            ("app_component", "frontend/src/scenes/insights/Insight.tsx", False),
            ("app_logic", "frontend/src/scenes/insights/insightLogic.ts", False),
        ]
    )
    def test_classification(self, _name: str, path: str, expected: bool) -> None:
        self.assertEqual(is_test_file(path), expected)


class TestFindGateFailures(unittest.TestCase):
    @parameterized.expand(
        [
            (
                "app_clone_at_bar_fails",
                make_clone("posthog/api/a.py", "posthog/api/b.py", APP_MAX_NEW_CLONE_TOKENS),
                True,
            ),
            (
                "test_clone_under_test_bar_passes",
                make_clone("posthog/api/test/test_a.py", "posthog/api/test/test_b.py", TEST_MAX_NEW_CLONE_TOKENS - 1),
                False,
            ),
            (
                "test_clone_at_test_bar_fails",
                make_clone("posthog/api/test/test_a.py", "posthog/api/test/test_b.py", TEST_MAX_NEW_CLONE_TOKENS),
                True,
            ),
            (
                "cross_boundary_uses_app_bar",
                make_clone("posthog/api/a.py", "posthog/api/test/test_b.py", APP_MAX_NEW_CLONE_TOKENS),
                True,
            ),
            (
                "pre_existing_clone_never_fails",
                make_clone("posthog/api/a.py", "posthog/api/b.py", 900, is_new=False),
                False,
            ),
            (
                "ts_app_clone_at_bar_fails",
                make_clone("frontend/src/a.ts", "frontend/src/b.ts", APP_MAX_NEW_CLONE_TOKENS, fmt="typescript"),
                True,
            ),
            (
                "ts_test_clone_under_test_bar_passes",
                make_clone("frontend/src/a.test.ts", "frontend/src/b.test.ts", TEST_MAX_NEW_CLONE_TOKENS - 1),
                False,
            ),
        ]
    )
    def test_gate(self, _name: str, clone: dict, expected_fails: bool) -> None:
        failures = find_gate_failures([clone])
        self.assertEqual(len(failures) == 1, expected_fails)

    def test_worst_first(self) -> None:
        small = make_clone("posthog/api/a.py", "posthog/api/b.py", 100)
        big = make_clone("posthog/api/c.py", "posthog/api/d.py", 900)
        failures = find_gate_failures([small, big])
        self.assertEqual([clone["tokens"] for clone, _ in failures], [900, 100])


class TestBuildFindings(unittest.TestCase):
    def test_partition_by_language(self) -> None:
        py = make_clone("posthog/api/a.py", "posthog/api/b.py", 200)
        ts = make_clone("frontend/src/a.ts", "frontend/src/b.ts", 200, fmt="typescript")
        tsx = make_clone("frontend/src/a.tsx", "frontend/src/b.tsx", 200, fmt="tsx")
        findings = build_findings(find_gate_failures([py, ts, tsx]))
        self.assertEqual([f["first_file"] for f in findings["python"]], ["posthog/api/a.py"])
        self.assertEqual([f["first_file"] for f in findings["typescript"]], ["frontend/src/a.ts", "frontend/src/a.tsx"])

    def test_finding_fields(self) -> None:
        clone = make_clone("posthog/api/a.py", "posthog/api/test/test_a.py", 200)
        (finding,) = build_findings(find_gate_failures([clone]))["python"]
        self.assertEqual(
            finding,
            {
                "first_file": "posthog/api/a.py",
                "first_start": 1,
                "first_end": 10,
                "second_file": "posthog/api/test/test_a.py",
                "second_start": 1,
                "second_end": 10,
                "lines": 10,
                "tokens": 200,
                "test": False,
            },
        )

    def test_clone_language_defaults_to_typescript_for_non_python(self) -> None:
        self.assertEqual(clone_language(make_clone("a.ts", "b.ts", 100, fmt="tsx")), "typescript")
        self.assertEqual(clone_language(make_clone("a.py", "b.py", 100)), "python")


if __name__ == "__main__":
    unittest.main()
