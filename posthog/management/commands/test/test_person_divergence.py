import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from parameterized import parameterized


class TestPersonDivergenceArguments(SimpleTestCase):
    @parameterized.expand([("zero", "0"), ("negative", "-5")])
    def test_scan_rejects_a_team_step_below_one(self, _name: str, team_step: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "hidden.csv"
            with self.assertRaisesMessage(CommandError, f"{team_step} must be 1 or more"):
                call_command("person_divergence", "scan", "hidden", "--output", str(output), "--team-step", team_step)
            assert not output.exists()
