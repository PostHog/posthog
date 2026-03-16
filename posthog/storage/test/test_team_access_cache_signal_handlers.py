from unittest.mock import MagicMock, patch

from django.test import TestCase

from posthog.storage.team_access_cache_signal_handlers import (
    capture_old_pak_secure_value,
    capture_old_secret_tokens,
    update_team_authentication_cache,
    update_team_authentication_cache_on_delete,
)


class TestCaptureOldPakSecureValue(TestCase):
    @patch("posthog.storage.team_access_cache_signal_handlers.PersonalAPIKey")
    def test_skips_unsaved_instance(self, mock_pak_cls):
        instance = MagicMock(pk=None)
        capture_old_pak_secure_value(instance)
        mock_pak_cls.objects.only.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.PersonalAPIKey")
    def test_captures_old_secure_value(self, mock_pak_cls):
        old_pak = MagicMock(secure_value="sha256$old_value")
        mock_pak_cls.objects.only.return_value.get.return_value = old_pak

        instance = MagicMock(pk=1)
        capture_old_pak_secure_value(instance)

        assert instance._old_secure_value == "sha256$old_value"

    @patch("posthog.storage.team_access_cache_signal_handlers.PersonalAPIKey")
    def test_captures_old_value_when_secure_value_in_update_fields(self, mock_pak_cls):
        old_pak = MagicMock(secure_value="sha256$old_value")
        mock_pak_cls.objects.only.return_value.get.return_value = old_pak

        instance = MagicMock(pk=1)
        capture_old_pak_secure_value(instance, update_fields=["secure_value"])

        assert instance._old_secure_value == "sha256$old_value"

    @patch("posthog.storage.team_access_cache_signal_handlers.PersonalAPIKey")
    def test_skips_db_read_for_non_auth_fields(self, mock_pak_cls):
        instance = MagicMock(pk=1)
        capture_old_pak_secure_value(instance, update_fields=["label"])
        mock_pak_cls.objects.only.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.PersonalAPIKey")
    def test_skips_db_read_for_last_used_at_only(self, mock_pak_cls):
        instance = MagicMock(pk=1)
        capture_old_pak_secure_value(instance, update_fields=["last_used_at"])
        mock_pak_cls.objects.only.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.PersonalAPIKey")
    def test_skips_when_pk_not_found(self, mock_pak_cls):
        mock_pak_cls.DoesNotExist = Exception
        mock_pak_cls.objects.only.return_value.get.side_effect = Exception("DoesNotExist")

        instance = MagicMock(pk=1)
        # Should not raise even if the key no longer exists in the DB
        capture_old_pak_secure_value(instance)


class TestCaptureOldSecretTokens(TestCase):
    @patch("posthog.storage.team_access_cache_signal_handlers.Team")
    def test_skips_unsaved_instance(self, mock_team_cls):
        instance = MagicMock(pk=None)
        capture_old_secret_tokens(instance)
        mock_team_cls.objects.only.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.Team")
    def test_captures_old_values_when_auth_fields_updated(self, mock_team_cls):
        old_team = MagicMock(secret_api_token="old_secret", secret_api_token_backup="old_backup")
        mock_team_cls.objects.only.return_value.get.return_value = old_team

        instance = MagicMock(pk=1)
        capture_old_secret_tokens(instance, update_fields=["secret_api_token"])

        assert instance._old_secret_api_token == "old_secret"
        assert instance._old_secret_api_token_backup == "old_backup"

    @patch("posthog.storage.team_access_cache_signal_handlers.Team")
    def test_skips_db_read_for_non_auth_fields(self, mock_team_cls):
        instance = MagicMock(pk=1)
        capture_old_secret_tokens(instance, update_fields=["name"])

        mock_team_cls.objects.only.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.Team")
    def test_captures_old_values_when_no_update_fields(self, mock_team_cls):
        old_team = MagicMock(secret_api_token="old_secret", secret_api_token_backup="old_backup")
        mock_team_cls.objects.only.return_value.get.return_value = old_team

        instance = MagicMock(pk=1)
        capture_old_secret_tokens(instance)

        assert instance._old_secret_api_token == "old_secret"
        assert instance._old_secret_api_token_backup == "old_backup"


class TestUpdateTeamAuthenticationCache(TestCase):
    @patch("posthog.storage.team_access_cache_signal_handlers.token_auth_cache")
    def test_skips_created_teams(self, mock_cache):
        instance = MagicMock(pk=1, api_token="phc_test")
        update_team_authentication_cache(instance, created=True)
        mock_cache.invalidate_token.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.token_auth_cache")
    def test_skips_teams_without_api_token(self, mock_cache):
        instance = MagicMock(pk=1, api_token="")
        update_team_authentication_cache(instance, created=False)
        mock_cache.invalidate_token.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.token_auth_cache")
    def test_skips_non_auth_update_fields(self, mock_cache):
        instance = MagicMock(pk=1, api_token="phc_test")
        instance._state.adding = False
        update_team_authentication_cache(instance, created=False, update_fields=["name"])
        mock_cache.invalidate_token.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.token_auth_cache")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_invalidates_discarded_backup_on_rotation(self, mock_hash, mock_cache):
        mock_hash.return_value = "sha256$hashed_old_backup"

        instance = MagicMock(pk=1, api_token="phc_test")
        instance._state.adding = False
        instance._old_secret_api_token_backup = "old_backup_value"
        instance.secret_api_token_backup = "new_backup_value"
        instance._old_secret_api_token = "same_secret"
        instance.secret_api_token = "same_secret"

        update_team_authentication_cache(instance, created=False)

        mock_hash.assert_called_once_with("old_backup_value", mode="sha256")
        mock_cache.invalidate_token.assert_called_once_with("sha256$hashed_old_backup")

    @patch("posthog.storage.team_access_cache_signal_handlers.token_auth_cache")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_invalidates_old_secret_on_direct_change(self, mock_hash, mock_cache):
        mock_hash.return_value = "sha256$hashed_old_secret"

        instance = MagicMock(pk=1, api_token="phc_test")
        instance._state.adding = False
        instance._old_secret_api_token = "old_secret_value"
        instance.secret_api_token = "new_secret_value"
        instance._old_secret_api_token_backup = None
        instance.secret_api_token_backup = None

        update_team_authentication_cache(instance, created=False)

        mock_hash.assert_called_once_with("old_secret_value", mode="sha256")
        mock_cache.invalidate_token.assert_called_once_with("sha256$hashed_old_secret")

    @patch("posthog.storage.team_access_cache_signal_handlers.token_auth_cache")
    def test_skips_old_secret_invalidation_when_it_becomes_backup(self, mock_cache):
        # During rotation: old primary → new backup. The token is still valid,
        # so we must NOT invalidate it.
        instance = MagicMock(pk=1, api_token="phc_test")
        instance._state.adding = False
        instance._old_secret_api_token = "rotating_out_primary"
        instance.secret_api_token = "brand_new_primary"
        instance._old_secret_api_token_backup = None
        instance.secret_api_token_backup = "rotating_out_primary"  # old primary is now backup

        update_team_authentication_cache(instance, created=False)

        mock_cache.invalidate_token.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.token_auth_cache")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_full_rotation_invalidates_only_discarded_backup(self, mock_hash, mock_cache):
        # Full rotation: new primary is set, old primary becomes backup, old backup is discarded.
        # Only the discarded backup should be invalidated; the old primary (now backup) stays valid.
        mock_hash.return_value = "sha256$hashed_old_backup"

        instance = MagicMock(pk=1, api_token="phc_test")
        instance._old_secret_api_token = "original_primary"
        instance.secret_api_token = "brand_new_primary"
        instance._old_secret_api_token_backup = "original_backup"
        instance.secret_api_token_backup = "original_primary"  # old primary promoted to backup

        update_team_authentication_cache(instance, created=False)

        mock_hash.assert_called_once_with("original_backup", mode="sha256")
        mock_cache.invalidate_token.assert_called_once_with("sha256$hashed_old_backup")

    @patch("posthog.storage.team_access_cache_signal_handlers.token_auth_cache")
    @patch("posthog.storage.team_access_cache_signal_handlers.capture_exception")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_captures_exception_on_failure(self, mock_hash, mock_capture, mock_cache):
        mock_hash.side_effect = Exception("Redis down")
        instance = MagicMock(pk=1, api_token="phc_test")
        instance._old_secret_api_token = "old_value"
        instance.secret_api_token = "new_value"
        instance._old_secret_api_token_backup = None
        instance.secret_api_token_backup = None

        update_team_authentication_cache(instance, created=False)

        mock_capture.assert_called_once()

    @patch("posthog.storage.team_access_cache_signal_handlers.token_auth_cache")
    def test_no_invalidation_when_tokens_unchanged(self, mock_cache):
        instance = MagicMock(pk=1, api_token="phc_test")
        instance._state.adding = False
        instance._old_secret_api_token = "same_value"
        instance.secret_api_token = "same_value"
        instance._old_secret_api_token_backup = "same_backup"
        instance.secret_api_token_backup = "same_backup"

        update_team_authentication_cache(instance, created=False)

        mock_cache.invalidate_token.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.token_auth_cache")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_skips_old_secret_invalidation_when_old_equals_new_secret(self, mock_hash, mock_cache):
        # old_secret == new secret_api_token but backup changed —
        # only backup should be invalidated, not the unchanged primary
        mock_hash.return_value = "sha256$hashed_old_backup"

        instance = MagicMock(pk=1, api_token="phc_test")
        instance._old_secret_api_token = "unchanged_token"
        instance.secret_api_token = "unchanged_token"
        instance._old_secret_api_token_backup = "old_backup"
        instance.secret_api_token_backup = "new_backup"

        update_team_authentication_cache(instance, created=False)

        mock_hash.assert_called_once_with("old_backup", mode="sha256")
        mock_cache.invalidate_token.assert_called_once_with("sha256$hashed_old_backup")


class TestUpdateTeamAuthenticationCacheOnDelete(TestCase):
    @patch("posthog.storage.team_access_cache_signal_handlers.token_auth_cache")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_invalidates_both_secret_tokens(self, mock_hash, mock_cache):
        mock_hash.side_effect = lambda v, mode="sha256": f"sha256${v}_hashed"
        instance = MagicMock(pk=42, secret_api_token="phs_main", secret_api_token_backup="phs_backup")
        update_team_authentication_cache_on_delete(instance)
        assert mock_cache.invalidate_token.call_count == 2
        mock_cache.invalidate_token.assert_any_call("sha256$phs_main_hashed")
        mock_cache.invalidate_token.assert_any_call("sha256$phs_backup_hashed")

    @patch("posthog.storage.team_access_cache_signal_handlers.token_auth_cache")
    def test_skips_instance_without_pk(self, mock_cache):
        instance = MagicMock(pk=None)
        update_team_authentication_cache_on_delete(instance)
        mock_cache.invalidate_token.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.token_auth_cache")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_skips_empty_tokens(self, mock_hash, mock_cache):
        instance = MagicMock(pk=42, secret_api_token="phs_main", secret_api_token_backup=None)
        mock_hash.return_value = "sha256$hashed"
        update_team_authentication_cache_on_delete(instance)
        mock_cache.invalidate_token.assert_called_once()

    @patch("posthog.storage.team_access_cache_signal_handlers.token_auth_cache")
    @patch("posthog.storage.team_access_cache_signal_handlers.capture_exception")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_captures_exception_on_failure(self, mock_hash, mock_capture, mock_cache):
        mock_hash.side_effect = Exception("Redis down")
        instance = MagicMock(pk=42, secret_api_token="phs_main", secret_api_token_backup=None)

        update_team_authentication_cache_on_delete(instance)

        mock_capture.assert_called_once()
