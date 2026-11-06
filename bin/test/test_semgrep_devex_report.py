#!/usr/bin/env python3

import io
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import unittest

from parameterized import parameterized

from bin.semgrep_devex_report import check_errors, main, print_backlog, ratchet_input, write_ratchet_input


def result(check_id: str, path: str, severity: str, line: int = 1) -> dict:
    return {
        "check_id": check_id,
        "path": path,
        "start": {"line": line},
        "extra": {"severity": severity, "message": f"{check_id} in {path}", "lines": "code()"},
    }


def report(results: list[dict], errors: list[dict] | None = None, scanned: list[str] | None = None) -> dict:
    return {"results": results, "errors": errors or [], "paths": {"scanned": scanned or []}}


class TestSemgrepDevexReport(unittest.TestCase):
    @parameterized.expand(
        [
            ("no_findings", [], ["products/desktop"], 0),
            ("warning_only", [result("warn", "posthog/a.py", "WARNING")], ["products/desktop"], 0),
            ("info_only", [result("integration-model-through-sdk", "ee/a.py", "INFO")], ["products/desktop"], 0),
            ("error", [result("bad", "posthog/a.py", "ERROR")], ["products/desktop"], 1),
            ("error_in_excluded_tree", [result("bad", "products/desktop/a.tsx", "ERROR")], ["products/desktop"], 0),
            (
                "error_next_to_an_excluded_prefix",
                [result("bad", "products/desktopx/a.py", "ERROR")],
                ["products/desktop/"],
                1,
            ),
        ]
    )
    def test_check_errors(self, _name: str, results: list[dict], excluded: list[str], expected: int) -> None:
        with redirect_stdout(io.StringIO()):
            self.assertEqual(check_errors(report(results), excluded), expected)

    def test_print_backlog_lists_only_the_warning_rules(self) -> None:
        found = report(
            [
                result("warn", "posthog/a.py", "WARNING"),
                result("bad", "posthog/b.py", "ERROR"),
                result("integration-model-through-sdk", "ee/c.py", "INFO"),
            ],
            scanned=["posthog/a.py", "posthog/b.py", "ee/c.py"],
        )
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(print_backlog(found), 0)
        printed = output.getvalue()
        self.assertIn("posthog/a.py:1", printed)
        # An ERROR finding either blocks in the next step, or sits under an excluded prefix where it
        # is accepted; the informational listing does not repeat it.
        self.assertNotIn("posthog/b.py:1", printed)
        self.assertNotIn("integration-model-through-sdk", printed)

    @parameterized.expand(
        [
            ("bare_id", "integration-model-through-sdk"),
            ("config_path_id", "semgrep.rules.devex.integration-model-through-sdk"),
        ]
    )
    def test_ratchet_input_keeps_one_rule_under_the_given_paths(self, _name: str, check_id: str) -> None:
        found = report(
            [
                result(check_id, "ee/api/integration.py", "INFO"),
                result(check_id, "ee/api/vercel/tasks.py", "INFO", line=12),
                result(check_id, "frontend/src/a.tsx", "INFO"),
                result("warn", "posthog/a.py", "WARNING"),
                # The same rule id as a suffix of another rule's id must not join the ratchet.
                result("not-integration-model-through-sdk", "ee/api/other.py", "INFO"),
            ],
            errors=[
                {"type": "Timeout", "path": "ee/api/slow.py"},
                {"type": "Timeout", "path": "tools/hogli/slow.py"},
                {"type": "ParseError", "spans": [{"file": "products/a.py"}]},
            ],
        )
        extracted = ratchet_input(found, "integration-model-through-sdk", ["common/", "ee/", "posthog/", "products/"])
        self.assertEqual(
            [item["path"] for item in extracted["results"]],
            ["ee/api/integration.py", "ee/api/vercel/tasks.py"],
        )
        # A file with a semgrep error cannot have its count called stale, so its error has to survive.
        self.assertEqual([error["type"] for error in extracted["errors"]], ["Timeout", "ParseError"])
        self.assertEqual(extracted["errors"][0]["path"], "ee/api/slow.py")
        self.assertEqual(extracted["errors"][1]["spans"], [{"file": "products/a.py"}])

    def test_write_ratchet_input_round_trips_through_the_ratchet_script(self) -> None:
        found = report([result("integration-model-through-sdk", "ee/api/integration.py", "INFO")])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "findings.json"
            with redirect_stdout(io.StringIO()):
                exit_code = write_ratchet_input(found, "integration-model-through-sdk", ["ee/"], output)
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.read_text())["results"][0]["path"], "ee/api/integration.py")

    def test_main_backlog_reads_the_report_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            findings = Path(directory) / "findings.json"
            findings.write_text(json.dumps(report([result("warn", "posthog/a.py", "WARNING")])))
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["backlog", "--findings", str(findings)]), 0)
            self.assertIn("posthog/a.py:1", output.getvalue())


if __name__ == "__main__":
    unittest.main()
