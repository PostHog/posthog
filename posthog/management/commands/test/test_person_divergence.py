import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from parameterized import parameterized


class TestPersonDivergenceArguments(SimpleTestCase):
    @parameterized.expand(
        [
            ("team_step_zero", ["hidden", "--team-step", "0"], "0 must be 1 or more"),
            ("team_step_negative", ["hidden", "--team-step", "-5"], "-5 must be 1 or more"),
            ("window_days_zero", ["stale", "--window-days", "0"], "0 must be 1 or more"),
            (
                "empty_team_range",
                ["hidden", "--min-team-id", "5", "--max-team-id", "5"],
                "--max-team-id must be above --min-team-id",
            ),
        ]
    )
    def test_scan_rejects_arguments_that_would_check_nothing(
        self, _name: str, scan_args: list[str], message: str
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "scan.csv"
            with self.assertRaisesMessage(CommandError, message):
                call_command("person_divergence", "scan", *scan_args, "--output", str(output))
            assert not output.exists()
