#!/usr/bin/env python3

import json
import tempfile
from collections import Counter
from pathlib import Path

import unittest

from parameterized import parameterized

from bin.semgrep_ratchet import compare, main, parse_baseline, render_baseline


def semgrep_output(*paths: str) -> dict:
    return {
        "results": [{"path": path, "check_id": "rule", "start": {"line": 1}} for path in paths],
        "errors": [],
    }


class TestSemgrepRatchet(unittest.TestCase):
    @parameterized.expand(
        [
            ("matches", Counter({"a.py": 2}), {"a.py": 2}, {}, {}),
            ("no_findings_no_baseline", Counter(), {}, {}, {}),
            ("new_file", Counter({"a.py": 1, "b.py": 1}), {"a.py": 1}, {"b.py": (1, 0)}, {}),
            ("more_in_a_listed_file", Counter({"a.py": 3}), {"a.py": 2}, {"a.py": (3, 2)}, {}),
            ("fewer_in_a_listed_file", Counter({"a.py": 1}), {"a.py": 2}, {}, {"a.py": (1, 2)}),
            ("file_fully_migrated", Counter(), {"a.py": 2}, {}, {"a.py": (0, 2)}),
            (
                "moved_file",
                Counter({"new/a.py": 2}),
                {"old/a.py": 2},
                {"new/a.py": (2, 0)},
                {"old/a.py": (0, 2)},
            ),
        ]
    )
    def test_compare(
        self,
        _name: str,
        findings: Counter[str],
        baseline: dict[str, int],
        expected_over: dict[str, tuple[int, int]],
        expected_stale: dict[str, tuple[int, int]],
    ) -> None:
        result = compare(findings, baseline)

        assert (result.over, result.stale) == (expected_over, expected_stale)

    @parameterized.expand(
        [
            ("no_count", "a.py\n"),
            ("zero_count", "a.py 0\n"),
            ("not_a_number", "a.py two\n"),
            ("repeated_path", "a.py 1\na.py 2\n"),
        ]
    )
    def test_parse_baseline_rejects_bad_lines(self, _name: str, text: str) -> None:
        with self.assertRaises(ValueError):
            parse_baseline(text)

    def test_render_keeps_the_header_and_round_trips(self) -> None:
        text = render_baseline("# header\n#\nold.py 9\n", Counter({"b.py": 1, "a b/c.py": 2}))

        assert text == "# header\n#\na b/c.py 2\nb.py 1\n"
        assert parse_baseline(text) == {"a b/c.py": 2, "b.py": 1}

    @parameterized.expand(
        [
            ("matches", ("a.py", "a.py"), "a.py 2\n", 0),
            ("new_finding", ("a.py", "a.py", "b.py"), "a.py 2\n", 1),
            ("stale_entry", ("a.py",), "a.py 2\n", 1),
        ]
    )
    def test_main_exit_code(self, _name: str, paths: tuple[str, ...], baseline: str, expected: int) -> None:
        with tempfile.TemporaryDirectory() as directory:
            findings_file = Path(directory) / "findings.json"
            baseline_file = Path(directory) / "baseline.txt"
            findings_file.write_text(json.dumps(semgrep_output(*paths)))
            baseline_file.write_text(baseline)

            exit_code = main(["--findings", str(findings_file), "--baseline", str(baseline_file)])

        assert exit_code == expected

    def test_main_update_writes_a_baseline_that_then_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            findings_file = Path(directory) / "findings.json"
            baseline_file = Path(directory) / "baseline.txt"
            findings_file.write_text(json.dumps(semgrep_output("a.py", "b.py", "a.py")))
            baseline_file.write_text("# header\nold.py 3\n")
            args = ["--findings", str(findings_file), "--baseline", str(baseline_file)]

            update_exit_code = main([*args, "--update"])
            check_exit_code = main(args)
            written = baseline_file.read_text()

        assert (update_exit_code, check_exit_code, written) == (0, 0, "# header\na.py 2\nb.py 1\n")
