from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command

from posthog.models.organization import Organization


class TestSyncToBilling(BaseTest):
    @patch("posthog.management.commands.sync_to_billing.capture_exception")
    @patch("posthog.management.commands.sync_to_billing.sync_members_to_billing")
    def test_a_failed_organization_does_not_stop_the_run(
        self, mock_sync: MagicMock, mock_capture_exception: MagicMock
    ) -> None:
        other = Organization.objects.create(name="Other")
        error = RuntimeError("billing is down")
        mock_sync.side_effect = [error, None]

        out = StringIO()
        with patch("sys.stdout", out):
            call_command(
                "sync_to_billing",
                action="organization_users",
                organization_ids=f"{self.organization.id},{other.id}",
            )

        assert {call.args[0] for call in mock_sync.call_args_list} == {self.organization.id, other.id}
        mock_capture_exception.assert_called_once()
        assert mock_capture_exception.call_args.args[0] is error
        assert "Done" in out.getvalue()
