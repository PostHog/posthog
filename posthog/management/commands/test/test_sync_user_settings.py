import os
from urllib.parse import urlparse

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.models import User
from posthog.models.file_system.file_system_shortcut import FileSystemShortcut
from posthog.models.user_home_settings import UserHomeSettings


class TestSyncUserSettingsCommand(BaseTest):
    def setUp(self):
        super().setUp()
        # Set up initial local user state
        self.user.theme_mode = "light"
        self.user.toolbar_mode = "toolbar"
        self.user.anonymize_data = False
        self.user.hedgehog_config = None
        self.user.save()

    def _mock_cloud_api_responses(self, mock_get):
        """Configure mock responses for PostHog cloud API"""
        # Mock user settings response
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {
            "id": 1,
            "email": "test@posthog.com",
            "theme_mode": "dark",
            "toolbar_mode": "disabled",
            "anonymize_data": True,
            "hedgehog_config": {"mode": "festive"},
            "partial_notification_settings": {"plugin_disabled": False},
            "has_seen_product_intro_for": {"feature_flags": True},
        }

        # Mock home settings response
        home_response = MagicMock()
        home_response.status_code = 200
        home_response.json.return_value = {
            "tabs": [{"id": "cloud_tab", "pathname": "/insights"}],
            "homepage": {"id": "cloud_home", "pathname": "/dashboard"},
        }

        # Mock shortcuts response
        shortcuts_response = MagicMock()
        shortcuts_response.status_code = 200
        shortcuts_response.json.return_value = {
            "results": [
                {"path": "cloud/path1", "type": "insight", "ref": "ref1", "href": "/insight/1"},
                {"path": "cloud/path2", "type": "dashboard", "ref": "ref2", "href": "/dashboard/2"},
            ]
        }

        # Configure mock to return different responses based on URL
        def side_effect(url, *args, **kwargs):
            if "users/@me" in url:
                return user_response
            elif "user_home_settings" in url:
                return home_response
            elif "file_system_shortcuts" in url:
                return shortcuts_response
            else:
                response = MagicMock()
                response.status_code = 404
                response.raise_for_status.side_effect = Exception("Not found")
                return response

        mock_get.side_effect = side_effect

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_all_settings(self, mock_get):
        """Test syncing all settings from cloud"""
        self._mock_cloud_api_responses(mock_get)

        call_command("sync_user_settings", api_key="test_key", host="https://app.posthog.com")

        # Verify user preferences were synced
        self.user.refresh_from_db()
        assert self.user.theme_mode == "dark"
        assert self.user.toolbar_mode == "disabled"
        assert self.user.anonymize_data is True
        assert self.user.hedgehog_config == {"mode": "festive"}

        # Verify home settings were synced
        home_settings = UserHomeSettings.objects.get(user=self.user, team=self.team)
        assert len(home_settings.tabs) == 1
        assert home_settings.tabs[0]["id"] == "cloud_tab"
        assert home_settings.homepage is not None
        assert home_settings.homepage["id"] == "cloud_home"

        # Verify shortcuts were synced
        shortcuts = FileSystemShortcut.objects.filter(user=self.user, team=self.team)
        assert shortcuts.count() == 2
        paths = {s.path for s in shortcuts}
        assert paths == {"cloud/path1", "cloud/path2"}

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_dry_run(self, mock_get):
        """Test that dry-run doesn't actually make changes"""
        self._mock_cloud_api_responses(mock_get)

        original_theme = self.user.theme_mode

        call_command("sync_user_settings", api_key="test_key", dry_run=True)

        # Nothing should change
        self.user.refresh_from_db()
        assert self.user.theme_mode == original_theme
        assert not UserHomeSettings.objects.filter(user=self.user, team=self.team).exists()
        assert FileSystemShortcut.objects.filter(user=self.user, team=self.team).count() == 0

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_with_env_var_api_key(self, mock_get):
        """Test using API key from environment variable"""
        self._mock_cloud_api_responses(mock_get)

        with patch.dict("os.environ", {"POSTHOG_PERSONAL_API_KEY": "env_key"}):
            call_command("sync_user_settings")

        # Verify it worked
        self.user.refresh_from_db()
        assert self.user.theme_mode == "dark"

    def test_sync_without_api_key_fails(self):
        """Test that command fails without API key"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(CommandError) as cm:
                call_command("sync_user_settings")

        assert "Personal API key required" in str(cm.value)

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_with_specific_local_email(self, mock_get):
        """Test syncing to a specific local user by email"""
        self._mock_cloud_api_responses(mock_get)

        # Create another user
        user2 = User.objects.create(email="user2@posthog.com")

        call_command("sync_user_settings", api_key="test_key", local_email="user2@posthog.com")

        # user2 should be updated
        user2.refresh_from_db()
        assert user2.theme_mode == "dark"

        # Original user should not be updated
        self.user.refresh_from_db()
        assert self.user.theme_mode == "light"

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_replaces_existing_shortcuts(self, mock_get):
        """Test that sync replaces existing shortcuts"""
        self._mock_cloud_api_responses(mock_get)

        # Create existing shortcuts
        FileSystemShortcut.objects.create(user=self.user, team=self.team, path="local/path", type="insight")

        call_command("sync_user_settings", api_key="test_key")

        # Should only have cloud shortcuts now
        shortcuts = FileSystemShortcut.objects.filter(user=self.user, team=self.team)
        assert shortcuts.count() == 2
        paths = {s.path for s in shortcuts}
        assert "local/path" not in paths
        assert "cloud/path1" in paths

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_updates_existing_home_settings(self, mock_get):
        """Test that sync updates existing home settings"""
        self._mock_cloud_api_responses(mock_get)

        # Create existing home settings
        UserHomeSettings.objects.create(
            user=self.user, team=self.team, tabs=[{"id": "local"}], homepage={"id": "local_home"}
        )

        call_command("sync_user_settings", api_key="test_key")

        # Should be updated, not duplicated
        assert UserHomeSettings.objects.filter(user=self.user, team=self.team).count() == 1
        home_settings = UserHomeSettings.objects.get(user=self.user, team=self.team)
        assert home_settings.tabs[0]["id"] == "cloud_tab"

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_handles_missing_home_settings(self, mock_get):
        """Test sync when cloud has no home settings"""

        def side_effect(url, *args, **kwargs):
            response = MagicMock()
            response.status_code = 200

            if "users/@me" in url:
                response.json.return_value = {"theme_mode": "dark"}
            elif "user_home_settings" in url:
                response.status_code = 404
                response.raise_for_status.side_effect = Exception("Not found")
            elif "file_system_shortcuts" in url:
                response.json.return_value = {"results": []}

            return response

        mock_get.side_effect = side_effect

        call_command("sync_user_settings", api_key="test_key")

        # User settings should still sync
        self.user.refresh_from_db()
        assert self.user.theme_mode == "dark"

        # No home settings should be created
        assert not UserHomeSettings.objects.filter(user=self.user, team=self.team).exists()

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_handles_empty_shortcuts(self, mock_get):
        """Test sync when cloud has no shortcuts"""

        def side_effect(url, *args, **kwargs):
            response = MagicMock()
            response.status_code = 200

            if "users/@me" in url:
                response.json.return_value = {"theme_mode": "dark"}
            elif "user_home_settings" in url:
                response.json.return_value = {"tabs": [], "homepage": {}}
            elif "file_system_shortcuts" in url:
                response.json.return_value = {"results": []}

            return response

        mock_get.side_effect = side_effect

        call_command("sync_user_settings", api_key="test_key")

        # Should not create any shortcuts
        assert FileSystemShortcut.objects.filter(user=self.user, team=self.team).count() == 0

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_with_custom_host(self, mock_get):
        """Test syncing from a custom PostHog host"""
        self._mock_cloud_api_responses(mock_get)

        call_command("sync_user_settings", api_key="test_key", host="https://eu.posthog.com")

        # Verify API was called with correct host
        calls = [call[0][0] for call in mock_get.call_args_list]
        assert any(urlparse(call).netloc == "eu.posthog.com" for call in calls)

    @parameterized.expand(
        [
            ("default_team", None, 2),
            ("custom_team", 99, 99),
        ]
    )
    def test_sync_uses_configurable_cloud_team_id(self, _name, override, expected_id):
        """Cloud team ID defaults to 2 but can be overridden"""
        with patch("posthog.management.commands.sync_user_settings.requests.get") as mock_get:
            self._mock_cloud_api_responses(mock_get)

            kwargs = {"api_key": "test_key"}
            if override is not None:
                kwargs["cloud_team_id"] = override

            call_command("sync_user_settings", **kwargs)

            urls = [call[0][0] for call in mock_get.call_args_list]
            base = f"/api/projects/{expected_id}"
            assert any(f"{base}/user_home_settings/" in url for url in urls)
            assert any(f"{base}/file_system_shortcuts/" in url for url in urls)

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_handles_api_error(self, mock_get):
        """Test that sync handles API errors gracefully"""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("API Error")
        mock_get.return_value = mock_response

        with pytest.raises(CommandError) as cm:
            call_command("sync_user_settings", api_key="test_key")

        assert "Failed to fetch user settings" in str(cm.value)

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_only_updates_changed_fields(self, mock_get):
        """Test that only changed fields are updated"""
        # Set user to have some values matching cloud
        self.user.theme_mode = "dark"  # This matches cloud
        self.user.toolbar_mode = "toolbar"  # This doesn't match
        self.user.save()

        self._mock_cloud_api_responses(mock_get)

        call_command("sync_user_settings", api_key="test_key")

        self.user.refresh_from_db()
        # Both should match cloud now
        assert self.user.theme_mode == "dark"
        assert self.user.toolbar_mode == "disabled"

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_excludes_deprecated_fields(self, mock_get):
        """Test that deprecated fields are not synced"""
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {
            "theme_mode": "dark",
            "events_column_config": {"active": "CLOUD"},  # DEPRECATED
            "email_opt_in": True,  # DEPRECATED
        }

        mock_get.return_value = user_response

        # Set deprecated fields locally
        self.user.events_column_config = {"active": "LOCAL"}
        self.user.email_opt_in = False
        self.user.save()

        call_command("sync_user_settings", api_key="test_key")

        self.user.refresh_from_db()
        # theme_mode should be synced
        assert self.user.theme_mode == "dark"
        # Deprecated fields should NOT be synced
        assert self.user.events_column_config == {"active": "LOCAL"}
        assert self.user.email_opt_in is False

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_all_users(self, mock_get):
        """Test syncing to all local users"""
        self._mock_cloud_api_responses(mock_get)

        # Create additional users
        user2 = User.objects.create(email="user2@posthog.com", theme_mode="light")
        user3 = User.objects.create(email="user3@posthog.com", theme_mode="light")

        call_command("sync_user_settings", api_key="test_key", all_users=True)

        # All users should be synced
        self.user.refresh_from_db()
        user2.refresh_from_db()
        user3.refresh_from_db()

        assert self.user.theme_mode == "dark"
        assert user2.theme_mode == "dark"
        assert user3.theme_mode == "dark"

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_all_users_with_team_specific_settings(self, mock_get):
        """Test that all users get team-specific settings synced"""
        self._mock_cloud_api_responses(mock_get)

        # Create additional user
        user2 = User.objects.create(email="user2@posthog.com")

        call_command("sync_user_settings", api_key="test_key", all_users=True)

        # Both users should have home settings
        home1 = UserHomeSettings.objects.filter(user=self.user, team=self.team).first()
        home2 = UserHomeSettings.objects.filter(user=user2, team=self.team).first()

        assert home1 is not None
        assert home2 is not None
        assert home1.tabs[0]["id"] == "cloud_tab"
        assert home2.tabs[0]["id"] == "cloud_tab"

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_all_users_ignores_local_email(self, mock_get):
        """Test that --all-users ignores --local-email"""
        self._mock_cloud_api_responses(mock_get)

        user2 = User.objects.create(email="user2@posthog.com", theme_mode="light")

        # local-email should be ignored when all-users is set
        call_command("sync_user_settings", api_key="test_key", all_users=True, local_email="nonexistent@test.com")

        # Both users should still be synced
        self.user.refresh_from_db()
        user2.refresh_from_db()

        assert self.user.theme_mode == "dark"
        assert user2.theme_mode == "dark"

    @patch("posthog.management.commands.sync_user_settings.requests.get")
    def test_sync_all_users_dry_run(self, mock_get):
        """Test dry-run with all-users"""
        self._mock_cloud_api_responses(mock_get)

        user2 = User.objects.create(email="user2@posthog.com", theme_mode="light")

        call_command("sync_user_settings", api_key="test_key", all_users=True, dry_run=True)

        # Nothing should change
        self.user.refresh_from_db()
        user2.refresh_from_db()

        assert self.user.theme_mode == "light"
        assert user2.theme_mode == "light"
