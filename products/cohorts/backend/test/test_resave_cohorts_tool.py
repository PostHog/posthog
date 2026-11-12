from io import TextIOBase
from urllib.parse import parse_qs, urlsplit

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib.admin.sites import site
from django.contrib.messages import get_messages
from django.core.management import CommandError
from django.test import RequestFactory

from parameterized import parameterized

from posthog.admin.admins.cohort_admin import CohortAdmin
from posthog.management.commands.resave_cohorts import UnclassifiedCohortsError

from products.cohorts.backend.console import MAX_OUTPUT_LINES
from products.cohorts.backend.models.cohort import Cohort

RUN_URL = "/admin/console/tools/resave-cohorts/run/"
RESYNC_URL = "/admin/console/tools/resave-cohorts/resync-static/"
CALL_COMMAND = "products.cohorts.backend.console.call_command"
RESYNC_TASK = "products.cohorts.backend.facade.api.insert_cohort_from_query"
SOURCE_QUERY = {"kind": "HogQLQuery", "query": "select person_id from events"}


class TestResaveCohortsTool(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def _messages(self, response) -> list[tuple[str, str]]:
        return [(message.level_tag, str(message)) for message in get_messages(response.wsgi_request)]

    def test_a_dry_run_shows_what_the_command_printed(self) -> None:
        response = self.client.post(RUN_URL, {"team_id": self.team.pk, "batch_size": 500, "dry_run": "on"}, follow=True)

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

        content = self.client.post(RUN_URL, {"batch_size": 500, "dry_run": "on"}, follow=True).content.decode()

        assert f"Showing the last {MAX_OUTPUT_LINES} of {MAX_OUTPUT_LINES + 50} lines." in content
        assert f"Processing team {MAX_OUTPUT_LINES + 50}" in content
        assert content.count("Processing team ") == MAX_OUTPUT_LINES

    def _cohort(self, name: str, is_static: bool, query: dict | None) -> Cohort:
        return Cohort.objects.create(team=self.team, name=name, is_static=is_static, query=query, count=42)

    @patch(RESYNC_TASK)
    def test_a_resync_previews_every_cohort_and_queues_only_the_static_ones(self, task: MagicMock) -> None:
        static = self._cohort("Static from query", is_static=True, query=SOURCE_QUERY)
        dynamic = self._cohort("Dynamic cohort", is_static=False, query=None)

        form = self.client.get(RESYNC_URL, {"cohort": [str(static.pk), str(dynamic.pk)]})
        preview = self.client.post(RESYNC_URL, {"cohorts": f"{static.pk}, {dynamic.pk}", "reason": "Stale members"})

        assert form.context["form"].initial["cohorts"] == f"{static.pk}\n{dynamic.pk}"
        assert preview.status_code == 200
        content = preview.content.decode()
        assert "Static from query" in content
        assert "Skip: not static" in content
        task.delay.assert_not_called()

        confirmed = self.client.post(RESYNC_URL, {"confirm_token": preview.context["confirm_token"]})

        assert confirmed.status_code == 302
        task.delay.assert_called_once_with(static.pk, self.team.pk)
        sent = self._messages(confirmed)
        assert ("warning", f"Skipped cohort {dynamic.pk} (Dynamic cohort): not static.") in sent
        assert (
            "success",
            f"Queued a re-sync for 1 cohort. Counts before the re-sync: cohort {static.pk} (Static from query): 42.",
        ) in sent

    @parameterized.expand(
        [
            ("not_static", False, SOURCE_QUERY),
            ("no_source_query", True, None),
            ("not_found", None, None),
        ]
    )
    @patch(RESYNC_TASK)
    def test_a_resync_with_no_static_cohort_to_resync_is_refused(
        self, _name: str, is_static: bool | None, query: dict | None, task: MagicMock
    ) -> None:
        cohort_id = 999999 if is_static is None else self._cohort("Picked cohort", is_static, query).pk

        response = self.client.post(RESYNC_URL, {"cohorts": str(cohort_id), "reason": "Stale members"})

        assert response.status_code == 400
        assert "None of these cohorts can be re-synced." in response.content.decode()
        task.delay.assert_not_called()

    @parameterized.expand([("within_the_limit", 2, True), ("over_the_limit", 1, False)])
    def test_the_admin_action_sends_the_picked_cohorts_to_the_console(
        self, _name: str, max_cohorts: int, expect_redirect: bool
    ) -> None:
        cohorts = [self._cohort(f"Picked cohort {index}", is_static=True, query=SOURCE_QUERY) for index in range(2)]
        admin = CohortAdmin(Cohort, site)

        with (
            patch("posthog.admin.admins.cohort_admin.MAX_STATIC_COHORT_RESYNCS", max_cohorts),
            patch.object(admin, "message_user") as message_user,
        ):
            response = admin.resync_static_cohort(
                request=RequestFactory().post("/"),
                queryset=Cohort.objects.filter(id__in=[cohort.pk for cohort in cohorts]),
            )

        if not expect_redirect:
            assert response is None
            assert "1 cohorts or fewer" in message_user.call_args.args[1]
            return
        message_user.assert_not_called()
        location = urlsplit(response["Location"])
        assert location.path == RESYNC_URL
        assert set(parse_qs(location.query)["cohort"]) == {str(cohort.pk) for cohort in cohorts}
