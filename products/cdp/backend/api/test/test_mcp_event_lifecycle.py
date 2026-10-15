from typing import TYPE_CHECKING

from unittest.mock import patch

if TYPE_CHECKING:
    pass


from products.cdp.backend.api.test.mcp_event_test_utils import MCPEventServiceTestCase
from products.cdp.backend.mcp_event_delivery import MCPCallbackError
from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionState
from products.cdp.backend.models.mcp_event_subscription import MCPEventSubscription


class TestMCPEventLifecycle(MCPEventServiceTestCase):
    def test_renewal_checks_destination_status_after_commit(self) -> None:
        subscription = self.subscribe()
        disabled = {"state": HogFunctionState.DISABLED.value}
        with (
            patch("products.cdp.backend.mcp_events.reload_hog_functions_on_workers"),
            patch("products.cdp.backend.models.hog_functions.hog_function.get_hog_function_status") as read_status,
            patch("products.cdp.backend.models.hog_functions.hog_function.patch_hog_function_status") as write_status,
        ):
            read_status.return_value.status_code = 200
            read_status.return_value.json.return_value = disabled
            write_status.return_value.status_code = 200
            write_status.return_value.json.return_value = {"state": HogFunctionState.DEGRADED.value}
            with self.captureOnCommitCallbacks(execute=True):
                self.subscribe()
                read_status.assert_not_called()
                write_status.assert_not_called()
            read_status.assert_called_once_with(self.team.pk, subscription.hog_function_id)
            write_status.assert_called_once_with(
                self.team.pk, subscription.hog_function_id, HogFunctionState.DEGRADED.value
            )

    def test_callback_failure_leaves_no_subscription_or_destination(self) -> None:
        with (
            patch("products.cdp.backend.mcp_events.verify_callback", side_effect=MCPCallbackError("timeout")),
            self.assertRaises(MCPCallbackError),
        ):
            self.subscribe()
        self.assertFalse(MCPEventSubscription.objects.for_team(self.team.pk).exists())
        self.assertFalse(HogFunction.objects.filter(team=self.team).exists())

    def test_deleting_subscriber_disables_the_managed_destination(self) -> None:
        subscription = self.subscribe()
        function_id = subscription.hog_function_id
        assert function_id is not None
        self.user.delete()
        function = HogFunction.objects.get(pk=function_id)
        self.assertFalse(function.enabled)
        self.assertFalse(function.encrypted_inputs)

    def test_worker_reload_is_scheduled_after_commit(self) -> None:
        with patch("products.cdp.backend.mcp_events.reload_hog_functions_on_workers") as reload:
            with self.captureOnCommitCallbacks(execute=True):
                subscription = self.subscribe()
                assert subscription.hog_function is not None
                reload.assert_not_called()
            reload.assert_called_once_with(team_id=self.team.pk, hog_function_ids=[str(subscription.hog_function_id)])
