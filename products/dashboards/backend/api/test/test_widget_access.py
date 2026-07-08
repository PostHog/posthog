from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from rest_framework.exceptions import PermissionDenied

from posthog.auth import IDJagAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.rbac.user_access_control import AccessControlLevel, UserAccessControl
from posthog.scopes import APIScopeObject

from products.dashboards.backend.models.dashboard_widget import DashboardWidget
from products.dashboards.backend.widget_access import (
    check_widget_tile_product_access,
    get_widget_api_scope_error,
    get_widget_product_access_error,
)
from products.dashboards.backend.widget_catalog import get_widget_product_access_denied_message
from products.dashboards.backend.widget_registry import WidgetRegistryEntry, get_widget_registry_entry


class TestWidgetAccess(BaseTest):
    def test_denied_message_for_known_product(self) -> None:
        message = get_widget_product_access_denied_message("error_tracking")
        self.assertEqual(message, "You do not have access to error tracking.")

    def test_denied_message_falls_back_for_unknown_product(self) -> None:
        message = get_widget_product_access_denied_message("future_product")
        self.assertEqual(message, "You do not have access to future product.")

    def test_registry_entry_without_product_access_allows(self) -> None:
        entry: WidgetRegistryEntry = {
            "query_fn": lambda team, config: {},
            "required_scopes": [],
        }

        self.assertIsNone(get_widget_product_access_error(entry, UserAccessControl(self.user, self.team)))

    def test_registry_entry_denies_without_product_access(self) -> None:
        entry = get_widget_registry_entry("error_tracking_list")
        assert entry is not None

        user_access_control = UserAccessControl(self.user, self.team)
        real_check = UserAccessControl.check_access_level_for_resource

        def deny_error_tracking_only(resource: APIScopeObject, required_level: AccessControlLevel = "viewer") -> bool:
            if resource == "error_tracking":
                return False
            return real_check(user_access_control, resource, required_level)

        with patch.object(
            user_access_control,
            "check_access_level_for_resource",
            side_effect=deny_error_tracking_only,
        ):
            self.assertEqual(
                get_widget_product_access_error(entry, user_access_control),
                "You do not have access to error tracking.",
            )

    def test_check_widget_tile_product_access_denies_unknown_widget_type(self) -> None:
        widget = DashboardWidget(widget_type="not_a_real_widget_type", config={}, team_id=self.team.id)
        user_access_control = UserAccessControl(self.user, self.team)

        with self.assertRaises(PermissionDenied) as raised:
            check_widget_tile_product_access(widget, user_access_control)

        self.assertIn("Unknown widget type", str(raised.exception))

    def test_get_widget_api_scope_error_allows_session_auth(self) -> None:
        entry = get_widget_registry_entry("error_tracking_list")
        assert entry is not None
        request = MagicMock()
        request.successful_authenticator = None

        self.assertIsNone(get_widget_api_scope_error(entry, request))

    def test_get_widget_api_scope_error_denies_missing_scope_on_pat(self) -> None:
        entry = get_widget_registry_entry("error_tracking_list")
        assert entry is not None
        authenticator = PersonalAPIKeyAuthentication()
        authenticator.personal_api_key = PersonalAPIKey(scopes=["dashboard:read"])
        request = MagicMock()
        request.successful_authenticator = authenticator

        self.assertEqual(
            get_widget_api_scope_error(entry, request),
            "API key missing required scope 'error_tracking:read'",
        )

    def test_get_widget_api_scope_error_allows_write_scope_for_read_requirement(self) -> None:
        entry = get_widget_registry_entry("error_tracking_list")
        assert entry is not None
        authenticator = PersonalAPIKeyAuthentication()
        authenticator.personal_api_key = PersonalAPIKey(scopes=["error_tracking:write"])
        request = MagicMock()
        request.successful_authenticator = authenticator

        self.assertIsNone(get_widget_api_scope_error(entry, request))

    def test_get_widget_api_scope_error_denies_missing_scope_on_id_jag(self) -> None:
        entry = get_widget_registry_entry("session_replay_list")
        assert entry is not None
        authenticator = IDJagAccessTokenAuthentication()
        authenticator.scopes = ["dashboard:read", "dashboard:write"]
        request = MagicMock()
        request.successful_authenticator = authenticator

        self.assertEqual(
            get_widget_api_scope_error(entry, request),
            "API key missing required scope 'session_recording:read'",
        )

    def test_get_widget_api_scope_error_allows_id_jag_with_required_scope(self) -> None:
        entry = get_widget_registry_entry("session_replay_list")
        assert entry is not None
        authenticator = IDJagAccessTokenAuthentication()
        authenticator.scopes = ["dashboard:write", "session_recording:read"]
        request = MagicMock()
        request.successful_authenticator = authenticator

        self.assertIsNone(get_widget_api_scope_error(entry, request))
