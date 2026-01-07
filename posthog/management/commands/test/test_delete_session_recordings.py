import os
import tempfile
from io import StringIO

import pytest
from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.session_recordings.models.session_recording import SessionRecording


class TestDeleteSessionRecordingsCommand(BaseTest):
    @parameterized.expand(
        [
            ("single_id", "session1", ["session1"]),
            ("multiple_ids", "session1,session2,session3", ["session1", "session2", "session3"]),
            ("with_spaces", "session1, session2 , session3", ["session1", "session2", "session3"]),
            ("with_duplicates", "session1,session1,session2", ["session1", "session2"]),
            ("with_empty_entries", "session1,,session2,", ["session1", "session2"]),
        ]
    )
    def test_parses_session_ids_from_arg(self, _name: str, session_ids_arg: str, expected_ids: list[str]):
        call_command(
            "delete_session_recordings",
            f"--team-id={self.team.id}",
            f"--session-ids={session_ids_arg}",
        )

        created_ids = set(
            SessionRecording.objects.filter(team=self.team, deleted=True).values_list("session_id", flat=True)
        )
        assert created_ids == set(expected_ids)

    @parameterized.expand(
        [
            ("without_header", "session1\nsession2\n\nsession3\n", False, {"session1", "session2", "session3"}),
            ("with_header", "session_id\nsession1\nsession2\nsession3\n", True, {"session1", "session2", "session3"}),
        ]
    )
    def test_parses_session_ids_from_csv_file(
        self, _name: str, csv_content: str, skip_header: bool, expected_ids: set[str]
    ):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            csv_path = f.name

        try:
            args = [
                "delete_session_recordings",
                f"--team-id={self.team.id}",
                f"--csv-file={csv_path}",
            ]
            if skip_header:
                args.append("--skip-header")

            call_command(*args)

            created_ids = set(
                SessionRecording.objects.filter(team=self.team, deleted=True).values_list("session_id", flat=True)
            )
            assert created_ids == expected_ids
        finally:
            os.unlink(csv_path)

    def test_updates_existing_recordings_to_deleted(self):
        SessionRecording.objects.create(team=self.team, session_id="existing1", deleted=False)
        SessionRecording.objects.create(team=self.team, session_id="existing2", deleted=None)

        call_command(
            "delete_session_recordings",
            f"--team-id={self.team.id}",
            "--session-ids=existing1,existing2",
        )

        assert SessionRecording.objects.get(session_id="existing1").deleted is True
        assert SessionRecording.objects.get(session_id="existing2").deleted is True

    def test_creates_new_recordings_with_deleted_true(self):
        call_command(
            "delete_session_recordings",
            f"--team-id={self.team.id}",
            "--session-ids=new1,new2",
        )

        new1 = SessionRecording.objects.get(session_id="new1")
        new2 = SessionRecording.objects.get(session_id="new2")

        assert new1.team == self.team
        assert new1.deleted is True
        assert new2.team == self.team
        assert new2.deleted is True

    def test_idempotent_running_twice_is_safe(self):
        call_command(
            "delete_session_recordings",
            f"--team-id={self.team.id}",
            "--session-ids=session1,session2",
        )

        first_run_count = SessionRecording.objects.filter(team=self.team, deleted=True).count()

        call_command(
            "delete_session_recordings",
            f"--team-id={self.team.id}",
            "--session-ids=session1,session2",
        )

        second_run_count = SessionRecording.objects.filter(team=self.team, deleted=True).count()

        assert first_run_count == second_run_count == 2

    def test_dry_run_does_not_modify_data(self):
        SessionRecording.objects.create(team=self.team, session_id="existing", deleted=False)

        out = StringIO()
        call_command(
            "delete_session_recordings",
            f"--team-id={self.team.id}",
            "--session-ids=existing,new_session",
            "--dry-run",
            stdout=out,
        )

        existing = SessionRecording.objects.get(session_id="existing")
        assert existing.deleted is False

        assert not SessionRecording.objects.filter(session_id="new_session").exists()

    def test_only_affects_specified_team(self):
        from posthog.models import Organization, Team

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        SessionRecording.objects.create(team=self.team, session_id="my_team_session", deleted=False)
        SessionRecording.objects.create(team=other_team, session_id="other_team_session", deleted=False)

        call_command(
            "delete_session_recordings",
            f"--team-id={self.team.id}",
            "--session-ids=my_team_session,other_team_session",
        )

        assert SessionRecording.objects.get(session_id="my_team_session").deleted is True
        assert SessionRecording.objects.get(session_id="other_team_session").deleted is False

    def test_handles_mixed_existing_and_new_recordings(self):
        SessionRecording.objects.create(team=self.team, session_id="existing", deleted=False)

        call_command(
            "delete_session_recordings",
            f"--team-id={self.team.id}",
            "--session-ids=existing,new",
        )

        assert SessionRecording.objects.get(session_id="existing").deleted is True
        assert SessionRecording.objects.get(session_id="new").deleted is True
        assert SessionRecording.objects.filter(team=self.team, deleted=True).count() == 2

    def test_raises_error_when_no_input_provided(self):
        with pytest.raises(CommandError) as cm:
            call_command(
                "delete_session_recordings",
                f"--team-id={self.team.id}",
            )
        assert "Must provide either --session-ids or --csv-file" in str(cm.value)

    def test_raises_error_when_both_inputs_provided(self):
        with pytest.raises(CommandError) as cm:
            call_command(
                "delete_session_recordings",
                f"--team-id={self.team.id}",
                "--session-ids=session1",
                "--csv-file=/tmp/test.csv",
            )
        assert "Provide only one of --session-ids or --csv-file" in str(cm.value)

    def test_raises_error_for_nonexistent_team(self):
        with pytest.raises(CommandError) as cm:
            call_command(
                "delete_session_recordings",
                "--team-id=999999",
                "--session-ids=session1",
            )
        assert "Team with ID 999999 does not exist" in str(cm.value)

    def test_raises_error_for_nonexistent_csv_file(self):
        with pytest.raises(CommandError) as cm:
            call_command(
                "delete_session_recordings",
                f"--team-id={self.team.id}",
                "--csv-file=/nonexistent/path/to/file.csv",
            )
        assert "CSV file not found" in str(cm.value)
