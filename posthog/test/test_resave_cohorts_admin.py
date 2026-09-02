from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import Client, override_settings

from parameterized import parameterized

from posthog.management.commands.resave_cohorts import UnclassifiedCohortsError


@override_settings(ADMIN_PORTAL_ENABLED=True)
class TestResaveCohortsAdminView(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def _post(self, team_id: str, follow: bool = False):
        return self.client.post("/admin/resave-cohorts/", {"batch_size": 500, "team_id": team_id}, follow=follow)

    @parameterized.expand(
        [
            ("explicit_team", "7", [7]),
            # Team 0 has to reach the command, which rejects it. Reading it as "no team given" would
            # silently resave every team.
            ("team_zero", "0", [0]),
            ("blank_team", "", None),
        ]
    )
    @patch("posthog.admin.admins.resave_cohorts_admin.call_command")
    def test_form_team_id_reaches_the_command(
        self, _name: str, submitted: str, expected: list[int] | None, mock_call_command: MagicMock
    ) -> None:
        self._post(submitted)

        assert mock_call_command.call_args.kwargs.get("team_id") == expected

    @patch("posthog.admin.admins.resave_cohorts_admin.call_command")
    def test_unclassified_cohorts_report_as_a_warning(self, mock_call_command: MagicMock) -> None:
        mock_call_command.side_effect = UnclassifiedCohortsError("2 cohorts still have a null condition_type: 1, 2")

        response = self._post("7", follow=True)

        message = next(iter(response.context["messages"]))
        assert message.level_tag == "warning"
        assert "finished" in str(message)

    @patch("posthog.admin.admins.resave_cohorts_admin.call_command")
    def test_a_run_that_never_started_reports_as_an_error(self, mock_call_command: MagicMock) -> None:
        mock_call_command.side_effect = Exception("boom")

        response = self._post("7", follow=True)

        message = next(iter(response.context["messages"]))
        assert message.level_tag == "error"
