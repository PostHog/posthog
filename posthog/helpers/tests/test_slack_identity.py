from unittest.mock import MagicMock

from django.core.cache import cache
from django.test import SimpleTestCase

from posthog.helpers.slack_identity import resolve_slack_profile_by_email, resolve_slack_user


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


def _client_resolving_email(name: str, avatar: str) -> MagicMock:
    client = MagicMock()
    client.users_lookupByEmail.return_value.data = {
        "ok": True,
        "user": {"profile": {"display_name": name, "image_72": avatar}},
    }
    return client


class TestSlackProfileByEmailWorkspaceNamespacing(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_same_email_in_different_workspaces_does_not_share_cache(self) -> None:
        # One address can belong to different people in two workspaces, and the resolved profile
        # decides whose name a message is posted under — so a shared entry posts as the wrong person.
        workspace_a_client = _client_resolving_email("Alice Internal", "https://example.com/alice.png")
        workspace_b_client = _client_resolving_email("Mallory External", "https://evil.example.com/mallory.png")

        resolved_a = resolve_slack_profile_by_email(workspace_a_client, "ada@example.com", workspace="T_A")
        resolved_b = resolve_slack_profile_by_email(workspace_b_client, "ada@example.com", workspace="T_B")

        assert resolved_a == {"name": "Alice Internal", "avatar": "https://example.com/alice.png"}
        assert resolved_b == {"name": "Mallory External", "avatar": "https://evil.example.com/mallory.png"}

        # Same workspace does hit the cache: no second API call.
        resolve_slack_profile_by_email(workspace_a_client, "ada@example.com", workspace="T_A")
        workspace_a_client.users_lookupByEmail.assert_called_once_with(email="ada@example.com")

    def test_unknown_workspace_bypasses_the_cache_instead_of_sharing_one_entry(self) -> None:
        client = _client_resolving_email("Ada", "https://example.com/ada.png")

        assert resolve_slack_profile_by_email(client, "ada@example.com", workspace=None) is not None
        resolve_slack_profile_by_email(client, "ada@example.com", workspace=None)

        # An unkeyed entry would be readable from every workspace, so nothing is cached at all.
        assert client.users_lookupByEmail.call_count == 2

    def test_unmatched_email_is_negative_cached_per_workspace(self) -> None:
        client = MagicMock()
        client.users_lookupByEmail.return_value.data = {"ok": False, "error": "users_not_found"}

        assert resolve_slack_profile_by_email(client, "nobody@example.com", workspace="T_A") is None
        assert resolve_slack_profile_by_email(client, "nobody@example.com", workspace="T_A") is None
        client.users_lookupByEmail.assert_called_once_with(email="nobody@example.com")

        assert resolve_slack_profile_by_email(client, "nobody@example.com", workspace="T_B") is None
        assert client.users_lookupByEmail.call_count == 2
