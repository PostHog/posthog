#!/usr/bin/env python3

import io
import subprocess
from contextlib import redirect_stdout

import unittest
from unittest.mock import patch

from parameterized import parameterized

from bin.check_uv_python_compatibility import check_flox_alignment, check_uv_python_compatibility, label_workflow_pins


class TestCheckUvPythonCompatibility(unittest.TestCase):
    @parameterized.expand(
        [
            ("supported", 0, "cpython-3.13.13\n", True),
            ("unsupported_returncode", 1, "", False),
            ("empty_output", 0, "", False),
        ]
    )
    def test_subprocess_result(self, _name, returncode, stdout, expected_compatible):
        completed = subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")
        with patch("bin.check_uv_python_compatibility.subprocess.run", return_value=completed):
            compatible, _message = check_uv_python_compatibility("0.11.28", "3.13.13")
        self.assertEqual(compatible, expected_compatible)

    @parameterized.expand(
        [
            ("timeout", subprocess.TimeoutExpired(cmd="uvx", timeout=30)),
            ("uvx_missing", FileNotFoundError()),
            ("unexpected_error", RuntimeError("boom")),
        ]
    )
    def test_subprocess_failure_assumes_compatible(self, _name, error):
        with patch("bin.check_uv_python_compatibility.subprocess.run", side_effect=error):
            compatible, _message = check_uv_python_compatibility("0.11.28", "3.13.13")
        self.assertTrue(compatible)


class TestLabelWorkflowPins(unittest.TestCase):
    def test_single_usage_uses_bare_name(self):
        missing, locations = label_workflow_pins({"ci-a.yml": ["0.11.28"]})
        self.assertEqual(missing, [])
        self.assertEqual(locations, {"0.11.28": ["ci-a.yml"]})

    def test_multiple_usages_get_suffix(self):
        missing, locations = label_workflow_pins({"ci-a.yml": ["0.11.28", "0.11.28"]})
        self.assertEqual(missing, [])
        self.assertEqual(locations, {"0.11.28": ["ci-a.yml (usage 1)", "ci-a.yml (usage 2)"]})

    def test_missing_and_divergent_pins(self):
        missing, locations = label_workflow_pins(
            {
                "ci-a.yml": ["0.11.28"],
                "ci-b.yml": [None],
                "ci-c.yml": ["0.10.2"],
            }
        )
        self.assertEqual(missing, ["ci-b.yml"])
        self.assertEqual(set(locations), {"0.11.28", "0.10.2"})


class TestCheckFloxAlignment(unittest.TestCase):
    @parameterized.expand(
        [
            ("single_entry_matches", {"uv": ("0.12.5", "all")}, True),
            ("single_entry_diverges", {"uv": ("0.11.25", "all")}, False),
            (
                "one_entry_lags_on_its_own_systems",
                {"uv": ("0.12.5", "aarch64-darwin"), "uv-x86_64-darwin": ("0.11.25", "x86_64-darwin")},
                True,
            ),
            ("every_entry_diverges", {"uv": ("0.11.28", "all"), "uv-old": ("0.11.25", "x86_64-darwin")}, False),
        ]
    )
    def test_alignment(self, _name, flox_entries, expected_ok):
        with patch("bin.check_uv_python_compatibility.get_uv_versions_from_flox", return_value=flox_entries):
            with redirect_stdout(io.StringIO()):
                ok = check_flox_alignment("0.12.5")
        self.assertEqual(ok, expected_ok)


if __name__ == "__main__":
    unittest.main()
