import os
import tempfile
from io import StringIO

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models import Organization, Team
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary


class TestDeleteSessionReplayEventsCommand(ClickhouseTestMixin, APIBaseTest):
    def _count_replay_events(self, team_id: int, session_ids: list[str]) -> int:
        result = sync_execute(
            """
            SELECT count(DISTINCT session_id)
            FROM session_replay_events
            WHERE team_id = %(team_id)s AND session_id IN %(session_ids)s
            """,
            {"team_id": team_id, "session_ids": session_ids},
        )
        return result[0][0] if result else 0

    def _create_replay(self, session_id: str, team_id: int | None = None) -> None:
        produce_replay_summary(
            session_id=session_id,
            team_id=team_id or self.team.pk,
            first_timestamp=now() - relativedelta(days=1),
            last_timestamp=now() - relativedelta(days=1),
            distinct_id="test_user",
            retention_period_days=30,
        )

    @parameterized.expand(
        [
            ("single_id", "session1", ["session1"]),
            ("multiple_ids", "session1,session2,session3", ["session1", "session2", "session3"]),
            ("with_spaces", "session1, session2 , session3", ["session1", "session2", "session3"]),
        ]
    )
    def test_deletes_session_replay_events(self, _name: str, session_ids_arg: str, expected_ids: list[str]):
        for sid in expected_ids:
            self._create_replay(sid)

        assert self._count_replay_events(self.team.pk, expected_ids) == len(expected_ids)

        call_command(
            "delete_session_replay_events",
            f"--team-id={self.team.id}",
            f"--session-ids={session_ids_arg}",
        )

        assert self._count_replay_events(self.team.pk, expected_ids) == 0

    @parameterized.expand(
        [
            ("without_header", "session1\nsession2\nsession3\n", False),
            ("with_header", "session_id\nsession1\nsession2\nsession3\n", True),
        ]
    )
    def test_parses_session_ids_from_csv_file(self, _name: str, csv_content: str, skip_header: bool):
        expected_ids = ["session1", "session2", "session3"]
        for sid in expected_ids:
            self._create_replay(sid)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            csv_path = f.name

        try:
            args = [
                "delete_session_replay_events",
                f"--team-id={self.team.id}",
                f"--csv-file={csv_path}",
            ]
            if skip_header:
                args.append("--skip-header")

            call_command(*args)

            assert self._count_replay_events(self.team.pk, expected_ids) == 0
        finally:
            os.unlink(csv_path)

    def test_dry_run_does_not_delete_data(self):
        self._create_replay("existing_session")

        out = StringIO()
        call_command(
            "delete_session_replay_events",
            f"--team-id={self.team.id}",
            "--session-ids=existing_session",
            "--dry-run",
            stdout=out,
        )

        assert self._count_replay_events(self.team.pk, ["existing_session"]) == 1
        assert "Would delete 1 sessions" in out.getvalue()

    def test_dry_run_reports_not_found(self):
        out = StringIO()
        call_command(
            "delete_session_replay_events",
            f"--team-id={self.team.id}",
            "--session-ids=nonexistent_session",
            "--dry-run",
            stdout=out,
        )

        output = out.getvalue()
        assert "Would delete 0 sessions" in output
        assert "Not found in ClickHouse: 1" in output

    def test_only_affects_specified_team(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        self._create_replay("my_session", team_id=self.team.pk)
        self._create_replay("other_session", team_id=other_team.pk)

        call_command(
            "delete_session_replay_events",
            f"--team-id={self.team.id}",
            "--session-ids=my_session,other_session",
        )

        assert self._count_replay_events(self.team.pk, ["my_session"]) == 0
        assert self._count_replay_events(other_team.pk, ["other_session"]) == 1

    def test_idempotent_running_twice_is_safe(self):
        self._create_replay("session1")

        call_command(
            "delete_session_replay_events",
            f"--team-id={self.team.id}",
            "--session-ids=session1",
        )

        call_command(
            "delete_session_replay_events",
            f"--team-id={self.team.id}",
            "--session-ids=session1",
        )

        assert self._count_replay_events(self.team.pk, ["session1"]) == 0

    def test_raises_error_when_no_input_provided(self):
        with self.assertRaises(CommandError) as cm:
            call_command(
                "delete_session_replay_events",
                f"--team-id={self.team.id}",
            )
        assert "Must provide either --session-ids or --csv-file" in str(cm.exception)

    def test_raises_error_when_both_inputs_provided(self):
        with self.assertRaises(CommandError) as cm:
            call_command(
                "delete_session_replay_events",
                f"--team-id={self.team.id}",
                "--session-ids=session1",
                "--csv-file=/tmp/test.csv",
            )
        assert "Provide only one of --session-ids or --csv-file" in str(cm.exception)

    def test_raises_error_for_nonexistent_team(self):
        with self.assertRaises(CommandError) as cm:
            call_command(
                "delete_session_replay_events",
                "--team-id=999999",
                "--session-ids=session1",
            )
        assert "Team with ID 999999 does not exist" in str(cm.exception)

    def test_raises_error_for_nonexistent_csv_file(self):
        with self.assertRaises(CommandError) as cm:
            call_command(
                "delete_session_replay_events",
                f"--team-id={self.team.id}",
                "--csv-file=/nonexistent/path/to/file.csv",
            )
        assert "CSV file not found" in str(cm.exception)
