from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.user import User
from posthog.storage.team_access_cache_signal_handlers import (
    capture_old_pak_secure_value,
    capture_old_psak_secure_value,
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
        # A real save fires every User receiver, and others (loop pausing on deactivation) also
        # schedule on_commit work; count only this handler's contribution.
        user_saved_commits = [
            call for call in mock_on_commit.call_args_list if "user_saved" in call.args[0].__qualname__
        ]
        self.assertEqual(len(user_saved_commits), 1)


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
            (["expires_at"], True, "expires_at only"),
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
