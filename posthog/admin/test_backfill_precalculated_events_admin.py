from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from parameterized import parameterized

from posthog.admin.admins.backfill_precalculated_events_admin import backfill_precalculated_events_view


def _attach_messages(request) -> None:
    request.session = {}
    request._messages = FallbackStorage(request)


class TestBackfillPrecalculatedEventsAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.factory = RequestFactory()

    @parameterized.expand([(True,), (False,)])
    def test_force_reprocess_checkbox_controls_command_flag(self, force_reprocess: bool) -> None:
        data = {"team_id": "2", "cohort_id": "123", "concurrent_workflows": "5"}
        if force_reprocess:
            data["force_reprocess"] = "on"
        request = self.factory.post("/admin/backfill-precalculated-events/", data)
        request.user = self.user
        _attach_messages(request)

        with (
            patch("posthog.admin.admins.backfill_precalculated_events_admin.call_command") as mock_call_command,
            patch("posthog.admin.admins.backfill_precalculated_events_admin.redirect") as mock_redirect,
        ):
            backfill_precalculated_events_view(request)

        mock_call_command.assert_called_once()
        command_args = mock_call_command.call_args[0]
        assert command_args[0] == "backfill_precalculated_events"
        assert ("--force-reprocess" in command_args) is force_reprocess
        mock_redirect.assert_called_once_with("backfill-precalculated-events")
