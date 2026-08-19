from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.activity_logging.activity_log import ActivityLog

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.services.hog_function_deletion import bulk_soft_delete_hog_functions


class TestBulkSoftDeleteHogFunctions(BaseTest):
    @patch("products.cdp.backend.services.hog_function_deletion.reload_hog_functions_on_workers")
    def test_soft_deletes_logs_system_activity_and_reloads_workers(self, mock_reload):
        function = HogFunction.objects.create(team=self.team, name="Downsample", type="transformation")

        with self.captureOnCommitCallbacks(execute=True):
            count = bulk_soft_delete_hog_functions([function])

        assert count == 1
        function.refresh_from_db()
        assert function.deleted is True

        log = ActivityLog.objects.get(scope="HogFunction", item_id=str(function.id))
        assert log.activity == "deleted"
        assert log.is_system is True
        assert log.user is None
        assert log.detail is not None
        assert log.detail["name"] == "Downsample"

        # A transformation is executable, so workers must be told to drop it.
        mock_reload.assert_called_once_with(team_id=self.team.id, hog_function_ids=[str(function.id)])

    @patch("products.cdp.backend.services.hog_function_deletion.reload_hog_functions_on_workers")
    def test_restore_logs_restored_activity(self, mock_reload):
        function = HogFunction.objects.create(team=self.team, name="Downsample", type="transformation", deleted=True)

        bulk_soft_delete_hog_functions([function], deleted=False)

        function.refresh_from_db()
        assert function.deleted is False
        assert ActivityLog.objects.get(scope="HogFunction", item_id=str(function.id)).activity == "restored"
