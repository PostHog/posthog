from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import Team

REFRESH_TASK = "products.cdp.backend.tasks.hog_functions.refresh_affected_hog_functions"


class TestHogFunctionRefreshDispatch(BaseTest):
    def test_team_save_defers_refresh_until_commit(self):
        with patch(REFRESH_TASK) as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                Team.objects.create(organization=self.organization, name="Deferred")
                # The dispatch must wait for the write to commit, not run inside its transaction.
                mock_task.delay.assert_not_called()
            mock_task.delay.assert_called_once_with(team_id=Team.objects.get(name="Deferred").id)

    def test_broker_error_during_refresh_does_not_fail_the_write(self):
        with patch(REFRESH_TASK) as mock_task:
            mock_task.delay.side_effect = RuntimeError("broker unreachable")
            with self.captureOnCommitCallbacks(execute=True):
                team = Team.objects.create(organization=self.organization, name="Survives")

        assert Team.objects.filter(id=team.id).exists()
