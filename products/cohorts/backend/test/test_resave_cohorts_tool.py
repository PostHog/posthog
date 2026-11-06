from io import TextIOBase

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib.messages import get_messages
from django.core.management import CommandError

from parameterized import parameterized

from posthog.management.commands.resave_cohorts import UnclassifiedCohortsError

from products.cohorts.backend.console import MAX_OUTPUT_LINES

RUN_URL = "/admin/console/tools/resave-cohorts/run/"
CALL_COMMAND = "products.cohorts.backend.console.call_command"


class TestResaveCohortsTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def _messages(self, response) -> list[tuple[str, str]]:
        return [(message.level_tag, str(message)) for message in get_messages(response.wsgi_request)]

    def test_a_dry_run_shows_what_the_command_printed(self) -> None:
        response = self.client.post(RUN_URL, {"team_id": self.team.pk, "batch_size": 500, "dry_run": "on"})

        assert response.status_code == 200
        content = response.content.decode()
        assert "Dry run, nothing was saved." in content
        assert f"Starting cohort resave for team {self.team.pk}" in content
        assert "Done (dry run)" in content

    @parameterized.expand(
        [
            ("explicit_team", "7", [7]),
            # Team 0 has to reach the command, which rejects it. Reading it as "no team given" would
            # re-save every team.
            ("team_zero", "0", [0]),
            ("blank_team", "", None),
        ]
    )
    @patch(CALL_COMMAND)
    def test_the_team_id_reaches_the_command(
        self, _name: str, submitted: str, expected: list[int] | None, call_command: MagicMock
    ) -> None:
        self.client.post(RUN_URL, {"batch_size": 500, "team_id": submitted})

        assert call_command.call_args.kwargs.get("team_id") == expected

    @parameterized.expand(
        [
            ("finished_with_problems", UnclassifiedCohortsError("2 cohorts still unclassified"), 302, "warning"),
            ("never_started", CommandError("No team with id 7"), 400, "error"),
        ]
    )
    @patch(CALL_COMMAND)
    def test_a_command_error_reports_what_happened(
        self, _name: str, error: CommandError, expected_status: int, expected_level: str, call_command: MagicMock
    ) -> None:
        call_command.side_effect = error

        response = self.client.post(RUN_URL, {"batch_size": 500, "team_id": "7"})

        assert response.status_code == expected_status
        assert any(level == expected_level and str(error) in text for level, text in self._messages(response))

    @parameterized.expand(
        [
            ("staff", True, "/admin/console/tools/resave-cohorts/?team_id=7"),
            ("signed_out", False, "/admin/login/"),
        ]
    )
    def test_the_old_admin_page_redirects_staff_to_the_tool(self, _name: str, signed_in: bool, expected: str) -> None:
        if not signed_in:
            self.client.logout()

        response = self.client.get("/admin/resave-cohorts/?team_id=7")

        assert response.status_code == 302
        assert response["Location"].startswith(expected)

    @patch(CALL_COMMAND)
    def test_a_long_dry_run_keeps_only_the_last_lines(self, call_command: MagicMock) -> None:
        def print_teams(*args: object, stdout: TextIOBase, **kwargs: object) -> None:
            for team in range(1, MAX_OUTPUT_LINES + 51):
                stdout.write(f"Processing team {team}\n")

        call_command.side_effect = print_teams

        content = self.client.post(RUN_URL, {"batch_size": 500, "dry_run": "on"}).content.decode()

        assert f"Showing the last {MAX_OUTPUT_LINES} of {MAX_OUTPUT_LINES + 50} lines." in content
        assert f"Processing team {MAX_OUTPUT_LINES + 50}" in content
        assert content.count("Processing team ") == MAX_OUTPUT_LINES
