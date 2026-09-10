#!/usr/bin/env python3

import io
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import unittest
from unittest.mock import patch

from parameterized import parameterized

from bin.check_uv_python_compatibility import check_uv_python_compatibility, check_workflow_pins, label_workflow_pins


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
    @parameterized.expand(
        [
            (".github/actions/setup-uv/action.yml", "'0.11.28' # exact", True),
            (".depot/actions/setup-uv/action.yaml", '"0.11.28"', True),
            (".github/workflows/ci.yml", "0.11.28", True),
            (".depot/workflows/ci.yaml", "'0.11.28'", True),
            (".depot/actions/setup-uv/action.yml", "'0.11.28.*'", False),
            (".github/actions/setup-uv/action.yml", "'>=0.11.28'", False),
            (".github/actions/setup-uv/action.yml", "'latest'", False),
            (".github/actions/setup-uv/action.yml", "'0.11.28, <0.12'", False),
        ]
    )
    def test_ci_pin_discovery(self, filename: str, version: str, expected_ok: bool) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ci_file = root / filename
            ci_file.parent.mkdir(parents=True)
            ci_file.write_text(
                f"steps:\n  - name: Install uv\n    uses: astral-sh/setup-uv@abc\n    with:\n      version: {version}\n"
            )
            with (
                patch("bin.check_uv_python_compatibility.__file__", str(root / "bin/check.py")),
                redirect_stdout(io.StringIO()),
            ):
                ok, pin = check_workflow_pins()
        self.assertEqual((ok, pin), (expected_ok, "0.11.28" if expected_ok else None))

    def test_missing_pin_does_not_read_next_step(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                "steps:\n"
                "  - uses: astral-sh/setup-uv@abc\n"
                "  - uses: another/setup@abc\n"
                "    with:\n"
                "      version: '0.11.28'\n"
            )
            with (
                patch("bin.check_uv_python_compatibility.__file__", str(root / "bin/check.py")),
                redirect_stdout(io.StringIO()),
            ):
                ok, pin = check_workflow_pins()
        self.assertFalse(ok)
        self.assertIsNone(pin)

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


if __name__ == "__main__":
    unittest.main()
