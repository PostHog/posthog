import csv
import tempfile
from io import StringIO
from pathlib import Path

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models.person.util import create_person as create_person_in_ch
from posthog.models.signals import mute_selected_signals
from posthog.test.persons import create_person


class TestPersonDivergenceCommand(ClickhouseTestMixin, BaseTest):
    def _ch_winner(self, person_uuid: str) -> tuple[int, int]:
        [[deleted, version]] = sync_execute(
            "SELECT argMax(is_deleted, version), max(version) FROM person WHERE team_id = %(team_id)s AND id = %(person_uuid)s",
            {"team_id": self.team.pk, "person_uuid": person_uuid},
        )
        return int(deleted), int(version)

    def _run(self, *args: str) -> list[dict[str, str]]:
        call_command("person_divergence", *args, stdout=StringIO())
        output = Path(args[args.index("--output") + 1])
        with output.open(newline="") as handle:
            return list(csv.DictReader(handle))

    def test_repair_reads_a_scan_csv_and_writes_only_with_apply(self) -> None:
        with mute_selected_signals():
            person = create_person(team=self.team, version=3)
        person_uuid = str(person.uuid)
        create_person_in_ch(team_id=self.team.pk, uuid=person_uuid, version=103, is_deleted=True)

        with tempfile.TemporaryDirectory() as tmp:
            team_range = ["--min-team-id", str(self.team.pk), "--max-team-id", str(self.team.pk + 1)]
            hidden = self._run("scan", "hidden", "--output", f"{tmp}/hidden.csv", *team_range)
            dry_run = self._run("repair", "--input", f"{tmp}/hidden.csv", "--output", f"{tmp}/dry.csv")
            dry_run_winner = self._ch_winner(person_uuid)
            applied = self._run("repair", "--input", f"{tmp}/hidden.csv", "--output", f"{tmp}/apply.csv", "--apply")
            with self.assertRaises(CommandError):
                self._run("repair", "--input", f"{tmp}/hidden.csv", "--output", f"{tmp}/apply.csv")

        assert [(row["person_uuid"], row["kind"]) for row in hidden] == [(person_uuid, "hidden")]
        assert [(row["outcome"], row["target_version"]) for row in dry_run] == [("would_repair", "104")]
        assert dry_run_winner == (1, 103)
        assert [row["outcome"] for row in applied] == ["repaired"]
        assert self._ch_winner(person_uuid) == (0, 104)


class TestPersonDivergenceArguments(SimpleTestCase):
    @parameterized.expand(
        [
            ("team_step_zero", ["hidden", "--team-step", "0"], "0 must be 1 or more"),
            ("team_step_negative", ["hidden", "--team-step", "-5"], "-5 must be 1 or more"),
            ("modulus_zero", ["sample", "--modulus", "0", "--residue", "0"], "0 must be 1 or more"),
            ("residue_at_modulus", ["sample", "--modulus", "4", "--residue", "4"], "--residue must be between 0 and 3"),
            ("residue_negative", ["sample", "--modulus", "4", "--residue", "-1"], "--residue must be between 0 and 3"),
            (
                "written_within_zero",
                ["sample", "--modulus", "4", "--residue", "0", "--written-within-days", "0"],
                "0 must be 1 or more",
            ),
            (
                "sample_size_zero",
                ["team", "--team-id", "1", "--before", "2026-01-01", "--sample-size", "0"],
                "0 must be 1 or more",
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

    def test_repair_names_the_line_of_a_short_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scan = Path(tmp) / "hidden.csv"
            scan.write_text("team_id,person_uuid\n1,0190f8e1-1234-7abc-89de-f0123456789a\n2\n")
            output = Path(tmp) / "dry.csv"
            with self.assertRaisesMessage(CommandError, f"{scan}:3:"):
                call_command("person_divergence", "repair", "--input", str(scan), "--output", str(output))
            assert not output.exists()
