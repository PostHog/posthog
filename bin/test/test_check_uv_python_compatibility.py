#!/usr/bin/env python3

import io
import subprocess
from contextlib import redirect_stdout

import unittest
from unittest.mock import patch

from parameterized import parameterized

from bin.check_uv_python_compatibility import (
    FloxUv,
    check_flox_alignment,
    check_uv_python_compatibility,
    label_workflow_pins,
)


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


PINNED = FloxUv(install_id="uv", version="0.12.5")
HELD_BACK = FloxUv(install_id="uv-x86_64-darwin", version="0.11.25")


class TestCheckFloxAlignment(unittest.TestCase):
    @parameterized.expand(
        [
            ("every_system_on_the_pin", {"aarch64-linux": PINNED, "x86_64-linux": PINNED}, True, "✓"),
            ("one_system_held_back", {"aarch64-linux": PINNED, "x86_64-darwin": HELD_BACK}, True, "⚠"),
            ("a_system_resolves_no_uv", {"aarch64-linux": PINNED, "x86_64-darwin": None}, False, "✗"),
            ("no_system_on_the_pin", {"aarch64-linux": HELD_BACK, "x86_64-darwin": HELD_BACK}, False, "✗"),
        ]
    )
    def test_alignment(self, _name, coverage, expected_ok, expected_marker):
        buffer = io.StringIO()
        with (
            patch("bin.check_uv_python_compatibility.get_uv_coverage_from_flox_lock", return_value=coverage),
            redirect_stdout(buffer),
        ):
            ok = check_flox_alignment("0.12.5")

        self.assertEqual(ok, expected_ok)
        self.assertIn(expected_marker, buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
