from unittest.mock import MagicMock

from django.core.cache import cache
from django.test import SimpleTestCase

from posthog.helpers.slack_identity import resolve_slack_user


def _client_returning(name: str, email: str) -> MagicMock:
    client = MagicMock()
    client.users_info.return_value.data = {
        "ok": True,
        "user": {"profile": {"display_name": name, "email": email, "image_72": None}},
    }
    return client


class TestSlackIdentityWorkspaceNamespacing(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_colliding_user_ids_in_different_workspaces_do_not_share_cache(self) -> None:
        workspace_a_client = _client_returning("Alice Internal", "alice@example.com")
        workspace_b_client = _client_returning("Mallory External", "mallory@evil.example.com")

        resolved_a = resolve_slack_user(workspace_a_client, "U12345", workspace="T_WORKSPACE_A")
        resolved_b = resolve_slack_user(workspace_b_client, "U12345", workspace="T_WORKSPACE_B")

        assert resolved_a["email"] == "alice@example.com"
        assert resolved_b["email"] == "mallory@evil.example.com"
        workspace_b_client.users_info.assert_called_once_with(user="U12345")

        # Same workspace does hit the cache: no second API call.
        resolve_slack_user(workspace_a_client, "U12345", workspace="T_WORKSPACE_A")
        workspace_a_client.users_info.assert_called_once_with(user="U12345")
