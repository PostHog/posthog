from datetime import timedelta

from unittest.mock import Mock, patch

from django.db import transaction
from django.utils import timezone

from parameterized import parameterized
from pydantic import JsonValue
from redis.exceptions import RedisError

from products.cdp.backend.api.test.mcp_event_test_utils import MCPEventServiceTestCase
from products.cdp.backend.mcp_event_delivery import MCPCallbackError
from products.cdp.backend.mcp_events import MCPEventSubscriptions
from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionState
from products.cdp.backend.models.mcp_event_subscription import MCPEventSubscription


class TestMCPEventLifecycle(MCPEventServiceTestCase):
    def test_renewal_checks_destination_status_after_commit(self) -> None:
        subscription = self.subscribe()
        disabled = {"state": HogFunctionState.DISABLED.value}
        with (
            patch("products.cdp.backend.tasks.mcp_events.reload_hog_functions_on_workers"),
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
        later_callback = Mock()
        with (
            patch(
                "products.cdp.backend.tasks.mcp_events.reload_hog_functions_on_workers",
                side_effect=RedisError("example publish failure"),
            ),
            patch("products.cdp.backend.tasks.mcp_events.retry_mcp_destination_reload.apply_async") as retry,
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.user.delete()
            transaction.on_commit(later_callback)
        retry.assert_called_once_with(
            kwargs={"team_id": self.team.pk, "hog_function_ids": [str(function_id)]}, countdown=1
        )
        later_callback.assert_called_once_with()
        function = HogFunction.objects.get(pk=function_id)
        self.assertFalse(function.enabled)
        self.assertFalse(function.encrypted_inputs)

    @parameterized.expand(["create", "renew", "stop", "expire"])
    def test_worker_reload_is_scheduled_once_after_commit(self, operation: str) -> None:
        subscription = self.subscribe() if operation != "create" else None
        if operation == "expire":
            assert subscription is not None
            subscription.expires_at = timezone.now() - timedelta(seconds=1)
            subscription.save(update_fields=["expires_at"])
        with (
            patch("products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers") as reload,
            patch("products.cdp.backend.tasks.mcp_events.reload_hog_functions_on_workers", new=reload),
            patch("products.cdp.backend.models.hog_functions.hog_function.get_hog_function_status") as read_status,
        ):
            read_status.return_value.status_code = 200
            read_status.return_value.json.return_value = {"state": HogFunctionState.DEGRADED.value}
            with self.captureOnCommitCallbacks(execute=True):
                if operation in {"create", "renew"}:
                    subscription = self.subscribe()
                elif operation == "stop":
                    self.unsubscribe()
                else:
                    self.assertEqual(MCPEventSubscriptions.expire(), 1)
                reload.assert_not_called()
            assert subscription is not None
            assert subscription.hog_function is not None
            subscription.refresh_from_db()
            subscription.hog_function.refresh_from_db()
            self.assertEqual(subscription.active, operation in {"create", "renew"})
            self.assertEqual(subscription.hog_function.enabled, subscription.active)
            reload.assert_called_once_with(team_id=self.team.pk, hog_function_ids=[str(subscription.hog_function_id)])

    def test_stop_uses_the_same_filter_identity_without_compiling(self) -> None:
        filters: dict[str, JsonValue] = {"events": [{"id": "example_event", "type": "events"}], "data_warehouse": []}
        self.payload["arguments"] = {"project_id": self.team.pk, "filters": filters}
        subscription = self.subscribe()
        with patch(
            "products.cdp.backend.models.hog_functions.hog_function.HogFunction._compile_filters",
            side_effect=AssertionError("Stopping must not compile filters"),
        ):
            self.unsubscribe()
        subscription.refresh_from_db()
        assert subscription.hog_function is not None
        self.assertFalse(subscription.active)
        self.assertFalse(subscription.hog_function.enabled)
