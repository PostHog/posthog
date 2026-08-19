from posthog.test.base import BaseTest

from posthog.models.activity_logging.activity_log import ActivityLog

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.services.hog_function_deletion import bulk_soft_delete_hog_functions


class TestBulkSoftDeleteHogFunctions(BaseTest):
    def test_soft_deletes_and_logs_system_activity(self):
        function = HogFunction.objects.create(team=self.team, name="Downsample", type="transformation")

        count = bulk_soft_delete_hog_functions([function])

        assert count == 1
        function.refresh_from_db()
        assert function.deleted is True

        log = ActivityLog.objects.get(scope="HogFunction", item_id=str(function.id))
        assert log.activity == "deleted"
        assert log.is_system is True
        assert log.user is None
        assert log.detail["name"] == "Downsample"

    def test_restore_logs_restored_activity(self):
        function = HogFunction.objects.create(team=self.team, name="Downsample", type="transformation", deleted=True)

        bulk_soft_delete_hog_functions([function], deleted=False)

        function.refresh_from_db()
        assert function.deleted is False
        assert ActivityLog.objects.get(scope="HogFunction", item_id=str(function.id)).activity == "restored"
