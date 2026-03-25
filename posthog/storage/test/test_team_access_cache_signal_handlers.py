from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.user import User
from posthog.storage.team_access_cache_signal_handlers import (
    _update_team_authentication_cache as update_team_authentication_cache,
    _update_team_authentication_cache_on_delete as update_team_authentication_cache_on_delete,
    capture_old_pak_secure_value,
    capture_old_psak_secure_value,
    capture_old_secret_tokens,
    organization_membership_deleted,
    organization_membership_saved,
    personal_api_key_deleted,
    personal_api_key_saved,
    project_secret_api_key_deleted,
    project_secret_api_key_saved,
    user_saved,
)


class TestCaptureOldPakSecureValue(TestCase):
    @patch("posthog.storage.team_access_cache_signal_handlers.PersonalAPIKey")
    def test_skips_unsaved_instance(self, mock_pak_cls):
        instance = MagicMock(pk=None)
        capture_old_pak_secure_value(instance)
        mock_pak_cls.objects.only.assert_not_called()

    def _existing_pak_instance(self, **kwargs):
        instance = MagicMock(**kwargs)
        instance._state.adding = False
        return instance

    @patch("posthog.storage.team_access_cache_signal_handlers.PersonalAPIKey")
    def test_captures_old_secure_value(self, mock_pak_cls):
        old_pak = MagicMock(secure_value="sha256$old_value")
        mock_pak_cls.objects.only.return_value.get.return_value = old_pak

        instance = self._existing_pak_instance(pk=1)
        capture_old_pak_secure_value(instance)

        assert instance._old_secure_value == "sha256$old_value"

    @patch("posthog.storage.team_access_cache_signal_handlers.PersonalAPIKey")
    def test_captures_old_value_when_secure_value_in_update_fields(self, mock_pak_cls):
        old_pak = MagicMock(secure_value="sha256$old_value")
        mock_pak_cls.objects.only.return_value.get.return_value = old_pak

        instance = self._existing_pak_instance(pk=1)
        capture_old_pak_secure_value(instance, update_fields=["secure_value"])

        assert instance._old_secure_value == "sha256$old_value"

    @patch("posthog.storage.team_access_cache_signal_handlers.PersonalAPIKey")
    def test_skips_db_read_for_non_auth_fields(self, mock_pak_cls):
        instance = self._existing_pak_instance(pk=1)
        capture_old_pak_secure_value(instance, update_fields=["label"])
        mock_pak_cls.objects.only.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.PersonalAPIKey")
    def test_skips_db_read_for_last_used_at_only(self, mock_pak_cls):
        instance = self._existing_pak_instance(pk=1)
        capture_old_pak_secure_value(instance, update_fields=["last_used_at"])
        mock_pak_cls.objects.only.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.PersonalAPIKey")
    def test_skips_when_pk_not_found(self, mock_pak_cls):
        PakDoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_pak_cls.DoesNotExist = PakDoesNotExist
        mock_pak_cls.objects.only.return_value.get.side_effect = PakDoesNotExist("not found")

        instance = self._existing_pak_instance(pk=1)
        capture_old_pak_secure_value(instance)

        assert "_old_secure_value" not in instance.__dict__

    @patch("posthog.storage.team_access_cache_signal_handlers.PersonalAPIKey")
    def test_skips_when_instance_is_adding(self, mock_pak_cls):
        instance = MagicMock(pk="random_token_abc")
        instance._state.adding = True
        capture_old_pak_secure_value(instance)
        mock_pak_cls.objects.only.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.PersonalAPIKey")
    def test_skips_db_query_when_old_value_already_stashed(self, mock_pak_cls):
        # SimpleNamespace gives a real __dict__; MagicMock stores attrs differently
        instance = SimpleNamespace(pk=1, _old_secure_value="already_stashed")
        instance._state = SimpleNamespace(adding=False)
        capture_old_pak_secure_value(instance)  # type: ignore[arg-type]
        mock_pak_cls.objects.only.assert_not_called()


class TestCaptureOldPsakSecureValue(TestCase):
    @patch("posthog.storage.team_access_cache_signal_handlers.ProjectSecretAPIKey")
    def test_skips_unsaved_instance(self, mock_psak_cls):
        instance = MagicMock(pk=None)
        capture_old_psak_secure_value(instance)
        mock_psak_cls.objects.only.assert_not_called()

    def _existing_psak_instance(self, **kwargs):
        instance = MagicMock(**kwargs)
        instance._state.adding = False
        return instance

    @patch("posthog.storage.team_access_cache_signal_handlers.ProjectSecretAPIKey")
    def test_captures_old_secure_value(self, mock_psak_cls):
        old_psak = MagicMock(secure_value="sha256$old_value")
        mock_psak_cls.objects.only.return_value.get.return_value = old_psak

        instance = self._existing_psak_instance(pk="key_abc")
        capture_old_psak_secure_value(instance)

        assert instance._old_secure_value == "sha256$old_value"

    @patch("posthog.storage.team_access_cache_signal_handlers.ProjectSecretAPIKey")
    def test_skips_db_read_for_non_auth_fields(self, mock_psak_cls):
        instance = self._existing_psak_instance(pk="key_abc")
        capture_old_psak_secure_value(instance, update_fields=["label"])
        mock_psak_cls.objects.only.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.ProjectSecretAPIKey")
    def test_skips_when_instance_is_adding(self, mock_psak_cls):
        instance = MagicMock(pk="random_token_abc")
        instance._state.adding = True
        capture_old_psak_secure_value(instance)
        mock_psak_cls.objects.only.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.ProjectSecretAPIKey")
    def test_skips_db_query_when_old_value_already_stashed(self, mock_psak_cls):
        # SimpleNamespace gives a real __dict__; MagicMock stores attrs differently
        instance = SimpleNamespace(pk="key_abc", _old_secure_value="already_stashed")
        instance._state = SimpleNamespace(adding=False)
        capture_old_psak_secure_value(instance)  # type: ignore[arg-type]
        mock_psak_cls.objects.only.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.ProjectSecretAPIKey")
    def test_skips_when_pk_not_found(self, mock_psak_cls):
        PsakDoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_psak_cls.DoesNotExist = PsakDoesNotExist
        mock_psak_cls.objects.only.return_value.get.side_effect = PsakDoesNotExist("not found")

        instance = self._existing_psak_instance(pk="key_abc")
        capture_old_psak_secure_value(instance)

        assert "_old_secure_value" not in instance.__dict__


class TestCaptureOldSecretTokens(TestCase):
    def _existing_team_instance(self, **kwargs):
        instance = MagicMock(**kwargs)
        instance._state.adding = False
        return instance

    @patch("posthog.storage.team_access_cache_signal_handlers.Team")
    def test_skips_unsaved_instance(self, mock_team_cls):
        instance = MagicMock(pk=None)
        capture_old_secret_tokens(instance)
        mock_team_cls.objects.only.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.Team")
    def test_captures_old_values_when_auth_fields_updated(self, mock_team_cls):
        old_team = MagicMock(secret_api_token="old_secret", secret_api_token_backup="old_backup")
        mock_team_cls.objects.only.return_value.get.return_value = old_team

        instance = self._existing_team_instance(pk=1)
        capture_old_secret_tokens(instance, update_fields=["secret_api_token"])

        assert instance._old_secret_api_token == "old_secret"
        assert instance._old_secret_api_token_backup == "old_backup"

    @patch("posthog.storage.team_access_cache_signal_handlers.Team")
    def test_skips_db_read_for_non_auth_fields(self, mock_team_cls):
        instance = self._existing_team_instance(pk=1)
        capture_old_secret_tokens(instance, update_fields=["name"])

        mock_team_cls.objects.only.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.Team")
    def test_captures_old_values_when_no_update_fields(self, mock_team_cls):
        old_team = MagicMock(secret_api_token="old_secret", secret_api_token_backup="old_backup")
        mock_team_cls.objects.only.return_value.get.return_value = old_team

        instance = self._existing_team_instance(pk=1)
        capture_old_secret_tokens(instance)

        assert instance._old_secret_api_token == "old_secret"
        assert instance._old_secret_api_token_backup == "old_backup"

    @patch("posthog.storage.team_access_cache_signal_handlers.Team")
    def test_skips_when_instance_is_adding(self, mock_team_cls):
        instance = MagicMock(pk=1)
        instance._state.adding = True
        capture_old_secret_tokens(instance)
        mock_team_cls.objects.only.assert_not_called()

    @patch("posthog.storage.team_access_cache_signal_handlers.Team")
    def test_skips_when_pk_not_found(self, mock_team_cls):
        TeamDoesNotExist = type("DoesNotExist", (Exception,), {})
        mock_team_cls.DoesNotExist = TeamDoesNotExist
        mock_team_cls.objects.only.return_value.get.side_effect = TeamDoesNotExist("not found")

        instance = self._existing_team_instance(pk=1)
        capture_old_secret_tokens(instance)

        assert "_old_secret_api_token" not in instance.__dict__
        assert "_old_secret_api_token_backup" not in instance.__dict__


class TestUpdateTeamAuthenticationCache(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    def test_skips_created_teams(self, mock_sync):
        instance = MagicMock(pk=1, api_token="phc_test")
        update_team_authentication_cache(instance, created=True)
        mock_sync.assert_not_called()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    def test_skips_teams_without_api_token(self, mock_sync):
        instance = MagicMock(pk=1, api_token="")
        update_team_authentication_cache(instance, created=False)
        mock_sync.assert_not_called()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_invalidates_discarded_backup_on_rotation(self, mock_hash, mock_sync):
        mock_hash.return_value = "sha256$hashed_old_backup"

        instance = MagicMock(pk=1, api_token="phc_test")

        instance._old_secret_api_token_backup = "old_backup_value"
        instance.secret_api_token_backup = "new_backup_value"
        instance._old_secret_api_token = "same_secret"
        instance.secret_api_token = "same_secret"

        update_team_authentication_cache(instance, created=False)

        mock_hash.assert_called_once_with("old_backup_value", mode="sha256")
        mock_sync.assert_called_once_with("sha256$hashed_old_backup")

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_invalidates_old_secret_on_direct_change(self, mock_hash, mock_sync):
        mock_hash.return_value = "sha256$hashed_old_secret"

        instance = MagicMock(pk=1, api_token="phc_test")

        instance._old_secret_api_token = "old_secret_value"
        instance.secret_api_token = "new_secret_value"
        instance._old_secret_api_token_backup = None
        instance.secret_api_token_backup = None

        update_team_authentication_cache(instance, created=False)

        mock_hash.assert_called_once_with("old_secret_value", mode="sha256")
        mock_sync.assert_called_once_with("sha256$hashed_old_secret")

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    def test_skips_old_secret_invalidation_when_it_becomes_backup(self, mock_sync):
        # During rotation: old primary -> new backup. The token is still valid,
        # so we must NOT invalidate it.
        instance = MagicMock(pk=1, api_token="phc_test")

        instance._old_secret_api_token = "rotating_out_primary"
        instance.secret_api_token = "brand_new_primary"
        instance._old_secret_api_token_backup = None
        instance.secret_api_token_backup = "rotating_out_primary"  # old primary is now backup

        update_team_authentication_cache(instance, created=False)

        mock_sync.assert_not_called()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_full_rotation_invalidates_only_discarded_backup(self, mock_hash, mock_sync):
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
        mock_sync.assert_called_once_with("sha256$hashed_old_backup")

    @patch("posthog.storage.team_access_cache_signal_handlers.capture_exception")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_captures_exception_on_failure(self, mock_hash, mock_capture):
        mock_hash.side_effect = Exception("Redis down")
        instance = MagicMock(pk=1, api_token="phc_test")

        instance._old_secret_api_token = "old_value"
        instance.secret_api_token = "new_value"
        instance._old_secret_api_token_backup = None
        instance.secret_api_token_backup = None

        update_team_authentication_cache(instance, created=False)

        mock_capture.assert_called_once()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    def test_no_invalidation_when_old_values_not_captured(self, mock_sync):
        # When pre_save was not called, the _old_* attrs are absent.
        # SimpleNamespace gives a real __dict__; MagicMock stores attrs differently
        instance = SimpleNamespace(pk=1, api_token="phc_test")
        update_team_authentication_cache(instance, created=False)  # type: ignore[arg-type]
        mock_sync.assert_not_called()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    def test_no_invalidation_when_tokens_unchanged(self, mock_sync):
        instance = MagicMock(pk=1, api_token="phc_test")

        instance._old_secret_api_token = "same_value"
        instance.secret_api_token = "same_value"
        instance._old_secret_api_token_backup = "same_backup"
        instance.secret_api_token_backup = "same_backup"

        update_team_authentication_cache(instance, created=False)

        mock_sync.assert_not_called()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_skips_old_secret_invalidation_when_old_equals_new_secret(self, mock_hash, mock_sync):
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
        mock_sync.assert_called_once_with("sha256$hashed_old_backup")


class TestUpdateTeamAuthenticationCacheOnDelete(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_invalidates_both_secret_tokens(self, mock_hash, mock_sync):
        mock_hash.side_effect = lambda v, mode="sha256": f"sha256${v}_hashed"
        instance = MagicMock(pk=42, secret_api_token="phs_main", secret_api_token_backup="phs_backup")
        update_team_authentication_cache_on_delete(instance)
        assert mock_sync.call_count == 2
        mock_sync.assert_any_call("sha256$phs_main_hashed")
        mock_sync.assert_any_call("sha256$phs_backup_hashed")

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    def test_skips_instance_without_pk(self, mock_sync):
        instance = MagicMock(pk=None)
        update_team_authentication_cache_on_delete(instance)
        mock_sync.assert_not_called()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_skips_empty_tokens(self, mock_hash, mock_sync):
        instance = MagicMock(pk=42, secret_api_token="phs_main", secret_api_token_backup=None)
        mock_hash.return_value = "sha256$hashed"
        update_team_authentication_cache_on_delete(instance)
        mock_sync.assert_called_once()

    @patch("posthog.storage.team_access_cache_signal_handlers.capture_exception")
    @patch("posthog.storage.team_access_cache_signal_handlers.hash_key_value")
    def test_captures_exception_on_failure(self, mock_hash, mock_capture):
        mock_hash.side_effect = Exception("Redis down")
        instance = MagicMock(pk=42, secret_api_token="phs_main", secret_api_token_backup=None)

        update_team_authentication_cache_on_delete(instance)

        mock_capture.assert_called_once()


class TestUserSavedSignalHandler(TestCase):
    @parameterized.expand(
        [
            # (created, is_active, original_is_active, should_schedule_update, description)
            # New user creation skips — no cached tokens to invalidate
            (True, True, True, False, "new user created"),
            (True, False, False, False, "new inactive user created"),
            # Existing user - is_active actually changed
            (False, False, True, True, "user deactivated"),
            (False, True, False, True, "user reactivated"),
            # Existing user - is_active unchanged (should NOT trigger)
            (False, True, True, False, "user saved but is_active unchanged (still active)"),
            (False, False, False, False, "user saved but is_active unchanged (still inactive)"),
        ]
    )
    @patch("django.db.transaction.on_commit")
    def test_user_saved_is_active_change_detection(
        self, created, is_active, original_is_active, should_schedule_update, description, mock_on_commit
    ):
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = is_active
        mock_user._original_is_active = original_is_active

        user_saved(sender=User, instance=mock_user, created=created)

        if should_schedule_update:
            mock_on_commit.assert_called_once()
        else:
            mock_on_commit.assert_not_called()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_user_tokens_sync")
    @patch("django.db.transaction.on_commit")
    def test_user_deactivated_uses_sync_invalidation(self, mock_on_commit, mock_sync_func):
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = False
        mock_user._original_is_active = True

        user_saved(sender=User, instance=mock_user, created=False)

        mock_on_commit.assert_called_once()
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        mock_sync_func.assert_called_once_with(42)

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_user_tokens_sync")
    @patch("django.db.transaction.on_commit")
    def test_user_activated_uses_sync_invalidation(self, mock_on_commit, mock_sync_func):
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = True
        mock_user._original_is_active = False

        user_saved(sender=User, instance=mock_user, created=False)

        mock_on_commit.assert_called_once()
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        mock_sync_func.assert_called_once_with(42)

    @patch("django.db.transaction.on_commit")
    def test_user_saved_fallback_when_original_is_active_absent(self, mock_on_commit):
        mock_user = MagicMock(spec=[])
        mock_user.id = 42
        mock_user.is_active = False
        # _original_is_active is NOT set (e.g. User not loaded via from_db)

        user_saved(sender=User, instance=mock_user, created=False)

        # Fallback: getattr returns is_active (False), matches current → no change detected
        mock_on_commit.assert_not_called()

    @patch("django.db.transaction.on_commit")
    def test_user_saved_updates_snapshot_to_prevent_double_fires(self, mock_on_commit):
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = False
        mock_user._original_is_active = True

        user_saved(sender=User, instance=mock_user, created=False)
        self.assertEqual(mock_on_commit.call_count, 1)
        self.assertEqual(mock_user._original_is_active, False)

        user_saved(sender=User, instance=mock_user, created=False)
        self.assertEqual(mock_on_commit.call_count, 1)

    @patch("django.db.transaction.on_commit")
    def test_from_db_sets_original_is_active_for_change_detection(self, mock_on_commit):
        user = User.objects.create(email="fromdb-test@example.com", is_active=True)
        mock_on_commit.reset_mock()

        loaded_user = User.objects.get(pk=user.pk)
        self.assertEqual(loaded_user._original_is_active, True)

        loaded_user.is_active = False
        loaded_user.save()
        mock_on_commit.assert_called_once()


class TestOrganizationMembershipSavedSignalHandler(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.invalidate_user_tokens_sync")
    @patch("django.db.transaction.on_commit")
    def test_schedules_invalidation_on_create(self, mock_on_commit, mock_sync_func):
        instance = MagicMock(user_id=42)
        organization_membership_saved(sender=OrganizationMembership, instance=instance, created=True)

        mock_on_commit.assert_called_once()
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        mock_sync_func.assert_called_once_with(42)

    @patch("django.db.transaction.on_commit")
    def test_skips_on_update(self, mock_on_commit):
        instance = MagicMock(user_id=42)
        organization_membership_saved(sender=OrganizationMembership, instance=instance, created=False)

        mock_on_commit.assert_not_called()

    @patch("django.db.transaction.on_commit")
    def test_skips_when_user_id_is_falsy(self, mock_on_commit):
        instance = MagicMock(user_id=None)
        organization_membership_saved(sender=OrganizationMembership, instance=instance, created=True)

        mock_on_commit.assert_not_called()


class TestOrganizationMembershipDeletedSignalHandler(TestCase):
    @patch("django.db.transaction.on_commit")
    def test_organization_membership_deleted_calls_update_when_user_removed(self, mock_on_commit):
        mock_membership = MagicMock()
        mock_membership.organization_id = "test-org-uuid"
        mock_membership.user_id = 42

        organization_membership_deleted(sender=OrganizationMembership, instance=mock_membership)

        mock_on_commit.assert_called_once()

    @patch("django.db.transaction.on_commit")
    def test_skips_when_user_id_is_falsy(self, mock_on_commit):
        mock_membership = MagicMock()
        mock_membership.user_id = None

        organization_membership_deleted(sender=OrganizationMembership, instance=mock_membership)

        mock_on_commit.assert_not_called()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_user_tokens_sync")
    @patch("django.db.transaction.on_commit")
    def test_organization_membership_deleted_uses_sync_invalidation(self, mock_on_commit, mock_sync_func):
        mock_membership = MagicMock()
        mock_membership.organization_id = "test-org-uuid"
        mock_membership.user_id = 42

        organization_membership_deleted(sender=OrganizationMembership, instance=mock_membership)

        mock_on_commit.assert_called_once()
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        mock_sync_func.assert_called_once_with(42)


class TestPersonalApiKeySavedSignalHandler(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    @patch("django.db.transaction.on_commit")
    def test_schedules_invalidation_on_save(self, mock_on_commit, mock_sync):
        instance = MagicMock(secure_value="sha256$abc123", user_id=42)
        instance._old_secure_value = None
        personal_api_key_saved(sender=PersonalAPIKey, instance=instance, created=False)

        mock_on_commit.assert_called_once()
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        mock_sync.assert_called_once_with("sha256$abc123")

    @patch("django.db.transaction.on_commit")
    def test_skips_invalidation_on_create(self, mock_on_commit):
        instance = MagicMock(secure_value="sha256$new_key", user_id=42)
        instance._old_secure_value = None
        personal_api_key_saved(sender=PersonalAPIKey, instance=instance, created=True)

        # Newly created keys are not cached yet; nothing to invalidate.
        mock_on_commit.assert_not_called()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    @patch("django.db.transaction.on_commit")
    def test_schedules_invalidation_for_old_and_new_value_when_key_rolled(self, mock_on_commit, mock_sync):
        instance = MagicMock(secure_value="sha256$new_value", user_id=42)
        instance._old_secure_value = "sha256$old_value"
        personal_api_key_saved(sender=PersonalAPIKey, instance=instance, created=False)

        assert mock_on_commit.call_count == 2
        for call in mock_on_commit.call_args_list:
            call[0][0]()

        mock_sync.assert_any_call("sha256$new_value")
        mock_sync.assert_any_call("sha256$old_value")

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    @patch("django.db.transaction.on_commit")
    def test_skips_old_value_invalidation_when_unchanged(self, mock_on_commit, mock_sync):
        instance = MagicMock(secure_value="sha256$same_value", user_id=42)
        instance._old_secure_value = "sha256$same_value"
        personal_api_key_saved(sender=PersonalAPIKey, instance=instance, created=False)

        # Only one on_commit call (for current value), not two (no old value invalidation)
        mock_on_commit.assert_called_once()
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        mock_sync.assert_called_once_with("sha256$same_value")

    @parameterized.expand(
        [
            (None, True, "no update_fields (full save)"),
            (["last_used_at"], False, "last_used_at only"),
            (["label"], False, "label only"),
            (["last_used_at", "label"], False, "last_used_at and label"),
            (["last_used_at", "secure_value"], True, "last_used_at and secure_value"),
            (["scopes"], True, "scopes only"),
            (["scoped_teams"], True, "scoped_teams only"),
            (["scoped_organizations"], True, "scoped_organizations only"),
            (["label", "scopes"], True, "label and scopes"),
        ]
    )
    @patch("django.db.transaction.on_commit")
    def test_update_fields_cache_relevant_guard(self, update_fields, should_schedule, description, mock_on_commit):
        instance = MagicMock(secure_value="sha256$abc123", user_id=42)
        instance._old_secure_value = None
        personal_api_key_saved(sender=PersonalAPIKey, instance=instance, created=False, update_fields=update_fields)

        if should_schedule:
            mock_on_commit.assert_called_once()
        else:
            mock_on_commit.assert_not_called()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    @patch("django.db.transaction.on_commit")
    def test_invalidates_only_old_value_when_secure_value_is_none(self, mock_on_commit, mock_sync):
        instance = MagicMock(secure_value=None, user_id=42)
        instance._old_secure_value = "sha256$old_value"
        personal_api_key_saved(sender=PersonalAPIKey, instance=instance, created=False)

        mock_on_commit.assert_called_once()
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        mock_sync.assert_called_once_with("sha256$old_value")

    @patch("django.db.transaction.on_commit")
    def test_skips_when_no_secure_value(self, mock_on_commit):
        instance = MagicMock(secure_value=None, user_id=42)
        instance._old_secure_value = None
        personal_api_key_saved(sender=PersonalAPIKey, instance=instance, created=False)

        mock_on_commit.assert_not_called()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_cache_task")
    @patch("posthog.tasks.team_access_cache_tasks.token_auth_cache")
    @patch("django.db.transaction.on_commit")
    def test_sync_failure_schedules_async_retry(self, mock_on_commit, mock_cache, mock_task):
        mock_cache.invalidate_token.side_effect = Exception("Redis down")
        instance = MagicMock(secure_value="sha256$abc123", user_id=42)
        instance._old_secure_value = None
        personal_api_key_saved(sender=PersonalAPIKey, instance=instance, created=False)

        mock_on_commit.assert_called_once()
        on_commit_callback = mock_on_commit.call_args[0][0]
        on_commit_callback()
        mock_task.apply_async.assert_called_once_with(args=["sha256$abc123"], countdown=5)


class TestPersonalApiKeyDeletedSignalHandler(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    @patch("django.db.transaction.on_commit")
    def test_schedules_invalidation_on_delete(self, mock_on_commit, mock_sync):
        instance = MagicMock(secure_value="sha256$abc123", user_id=42)
        personal_api_key_deleted(sender=PersonalAPIKey, instance=instance)

        mock_on_commit.assert_called_once()
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        mock_sync.assert_called_once_with("sha256$abc123")

    @patch("django.db.transaction.on_commit")
    def test_skips_when_no_secure_value(self, mock_on_commit):
        instance = MagicMock(secure_value=None, user_id=42)
        personal_api_key_deleted(sender=PersonalAPIKey, instance=instance)

        mock_on_commit.assert_not_called()


class TestProjectSecretApiKeySavedSignalHandler(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    @patch("django.db.transaction.on_commit")
    def test_schedules_invalidation_on_update(self, mock_on_commit, mock_sync):
        instance = MagicMock(secure_value="sha256$abc123")
        instance._old_secure_value = None
        project_secret_api_key_saved(sender=ProjectSecretAPIKey, instance=instance, created=False)

        mock_on_commit.assert_called_once()
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        mock_sync.assert_called_once_with("sha256$abc123")

    @patch("django.db.transaction.on_commit")
    def test_skips_invalidation_on_create(self, mock_on_commit):
        instance = MagicMock(secure_value="sha256$new_key")
        instance._old_secure_value = None
        project_secret_api_key_saved(sender=ProjectSecretAPIKey, instance=instance, created=True)

        mock_on_commit.assert_not_called()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    @patch("django.db.transaction.on_commit")
    def test_schedules_invalidation_for_old_and_new_value_when_key_rolled(self, mock_on_commit, mock_sync):
        instance = MagicMock(secure_value="sha256$new_value")
        instance._old_secure_value = "sha256$old_value"
        project_secret_api_key_saved(sender=ProjectSecretAPIKey, instance=instance, created=False)

        assert mock_on_commit.call_count == 2
        for call in mock_on_commit.call_args_list:
            call[0][0]()

        mock_sync.assert_any_call("sha256$new_value")
        mock_sync.assert_any_call("sha256$old_value")

    @parameterized.expand(
        [
            (None, True, "no update_fields (full save)"),
            (["last_used_at"], False, "last_used_at only"),
            (["label"], False, "label only"),
            (["secure_value"], True, "secure_value only"),
            (["scopes"], True, "scopes only"),
            (["label", "scopes"], True, "label and scopes"),
        ]
    )
    @patch("django.db.transaction.on_commit")
    def test_update_fields_cache_relevant_guard(self, update_fields, should_schedule, description, mock_on_commit):
        instance = MagicMock(secure_value="sha256$abc123")
        instance._old_secure_value = None
        project_secret_api_key_saved(
            sender=ProjectSecretAPIKey, instance=instance, created=False, update_fields=update_fields
        )

        if should_schedule:
            mock_on_commit.assert_called_once()
        else:
            mock_on_commit.assert_not_called()


class TestProjectSecretApiKeyDeletedSignalHandler(TestCase):
    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    @patch("django.db.transaction.on_commit")
    def test_schedules_invalidation_on_delete(self, mock_on_commit, mock_sync):
        instance = MagicMock(secure_value="sha256$abc123")
        project_secret_api_key_deleted(sender=ProjectSecretAPIKey, instance=instance)

        mock_on_commit.assert_called_once()
        on_commit_lambda = mock_on_commit.call_args[0][0]
        on_commit_lambda()

        mock_sync.assert_called_once_with("sha256$abc123")

    @patch("django.db.transaction.on_commit")
    def test_skips_when_no_secure_value(self, mock_on_commit):
        instance = MagicMock(secure_value=None)
        project_secret_api_key_deleted(sender=ProjectSecretAPIKey, instance=instance)

        mock_on_commit.assert_not_called()
