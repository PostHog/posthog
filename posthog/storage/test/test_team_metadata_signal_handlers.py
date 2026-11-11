import json
from collections.abc import Callable

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.db import transaction
from django.test import override_settings

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_secret, hash_key_value
from posthog.storage import object_storage
from posthog.storage.team_access_cache import TOKEN_CACHE_PREFIX, token_auth_cache
from posthog.storage.team_metadata_cache import team_metadata_hypercache, update_team_metadata_cache

from products.feature_flags.backend.models.team_feature_flag_policy_config import TeamFeatureFlagPolicyConfig


@override_settings(FLAGS_REDIS_URL="redis://localhost:6379")
class TestTeamMetadataInvalidationSignals(BaseTest):
    def test_organization_rename_enqueues_fanout(self) -> None:
        with patch("posthog.tasks.team_metadata.update_related_teams_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                self.organization.name = "Renamed org"
                self.organization.save()

        mock_task.delay.assert_called_once_with(organization_id=self.organization.id, project_id=None)

    def test_project_rename_enqueues_fanout(self) -> None:
        with patch("posthog.tasks.team_metadata.update_related_teams_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                self.project.name = "Renamed project"
                self.project.save()

        mock_task.delay.assert_called_once_with(organization_id=None, project_id=self.project.id)

    def test_save_with_name_in_update_fields_enqueues(self) -> None:
        with patch("posthog.tasks.team_metadata.update_related_teams_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                self.organization.name = "Renamed via update_fields"
                self.organization.save(update_fields=["name"])

        mock_task.delay.assert_called_once_with(organization_id=self.organization.id, project_id=None)

    def test_save_without_name_in_update_fields_does_not_enqueue(self) -> None:
        with patch("posthog.tasks.team_metadata.update_related_teams_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                self.organization.is_member_join_email_enabled = False
                self.organization.save(update_fields=["is_member_join_email_enabled"])

        mock_task.delay.assert_not_called()

    def test_creating_does_not_enqueue(self) -> None:
        with patch("posthog.tasks.team_metadata.update_related_teams_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                Organization.objects.create(name="Brand new org")
                Project.objects.create_with_team(
                    organization=self.organization, initiating_user=self.user, name="Brand new project"
                )

        mock_task.delay.assert_not_called()

    @override_settings(FLAGS_REDIS_URL="")
    def test_no_fanout_when_flags_redis_url_unset(self) -> None:
        with patch("posthog.tasks.team_metadata.update_related_teams_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                self.organization.name = "Renamed org"
                self.organization.save()
                self.project.name = "Renamed project"
                self.project.save()

        mock_task.delay.assert_not_called()

    def test_enqueue_failure_records_counter_and_does_not_propagate(self) -> None:
        with patch("posthog.tasks.team_metadata.update_related_teams_metadata_cache_task") as mock_task:
            mock_task.delay.side_effect = Exception("broker down")
            with patch(
                "posthog.storage.team_metadata_signal_handlers.HYPERCACHE_SIGNAL_UPDATE_COUNTER"
            ) as mock_counter:
                try:
                    with self.captureOnCommitCallbacks(execute=True):
                        self.organization.name = "Renamed org"
                        self.organization.save(update_fields=["name"])
                except Exception:
                    self.fail("enqueue failure should not propagate to the caller")

        mock_counter.labels.assert_called_once_with(
            namespace="team_metadata", cache_name="team_metadata", operation="enqueue", result="failure"
        )
        mock_counter.labels.return_value.inc.assert_called_once_with()


@override_settings(FLAGS_REDIS_URL="redis://localhost:6379")
class TestRetiredTokenTeamMetadataClear(BaseTest):
    def test_deleting_project_clears_team_metadata_via_cascade(self) -> None:
        project, team = Project.objects.create_with_team(
            organization=self.organization, initiating_user=self.user, name="Doomed project"
        )
        team_id = team.id

        # Capture ids at call time: the delete collector nulls each instance's pk after deletion,
        # so reading instance.id after project.delete() returns would see None.
        cleared_team_ids: set[int] = set()
        with patch(
            "posthog.storage.team_metadata_signal_handlers.clear_team_metadata_cache",
            side_effect=lambda instance, **kwargs: cleared_team_ids.add(instance.id),
        ):
            project.delete()

        self.assertIn(team_id, cleared_team_ids)

    @parameterized.expand(
        [
            ("team_delete", lambda team, user: team.delete()),
            ("token_reset", lambda team, user: team.reset_token_and_save(user=user, is_impersonated_session=False)),
        ]
    )
    @patch("posthog.tasks.integrations.push_vercel_secrets.delay")
    def test_retiring_token_clears_its_team_metadata_cache_in_redis_and_s3(
        self, _name: str, retire_token: Callable[[Team, User], None], _mock_push_vercel: Mock
    ) -> None:
        update_team_metadata_cache(self.team)
        api_token = self.team.api_token
        cache_key = team_metadata_hypercache.get_cache_key(api_token)
        assert team_metadata_hypercache.cache_client.get(cache_key) is not None
        assert object_storage.read(cache_key, missing_ok=True) is not None

        with self.captureOnCommitCallbacks(execute=True):
            retire_token(self.team, self.user)
            # This write stands in for a refresh that writes the old token's entry before the commit.
            team_metadata_hypercache.set_cache_value(api_token, {"api_token": api_token})

        assert team_metadata_hypercache.cache_client.get(cache_key) is None
        assert object_storage.read(cache_key, missing_ok=True) is None

    @patch("posthog.tasks.integrations.push_vercel_secrets.delay")
    def test_token_reset_drops_the_secret_key_auth_entry(self, _mock_push_vercel: Mock) -> None:
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save()
        auth_key = f"{TOKEN_CACHE_PREFIX}{hash_key_value(self.team.secret_api_token, mode='sha256')}"
        token_auth_cache.redis.setex(auth_key, 300, json.dumps({"type": "secret", "api_token": self.team.api_token}))

        with self.captureOnCommitCallbacks(execute=True):
            self.team.reset_token_and_save(user=self.user, is_impersonated_session=False)

        assert not token_auth_cache.redis.exists(auth_key)

    @patch("posthog.tasks.team_metadata.clear_team_metadata_cache_for_token_task.delay")
    @patch("posthog.tasks.integrations.push_vercel_secrets.delay")
    def test_rolled_back_token_reset_does_not_enqueue_the_clear(
        self, _mock_push_vercel: Mock, mock_clear: Mock
    ) -> None:
        with self.captureOnCommitCallbacks(execute=True), self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.team.reset_token_and_save(user=self.user, is_impersonated_session=False)
                raise RuntimeError("roll back the reset")

        mock_clear.assert_not_called()

    @patch("posthog.tasks.team_access_cache_tasks.invalidate_team_tokens_task.apply_async")
    @patch("posthog.tasks.team_metadata.clear_team_metadata_cache_for_token_task.delay")
    @patch("posthog.tasks.integrations.push_vercel_secrets.delay")
    def test_failed_auth_drop_on_token_reset_retries_and_still_enqueues_the_clear(
        self, _mock_push_vercel: Mock, mock_clear: Mock, mock_auth_retry: Mock
    ) -> None:
        old_token = self.team.api_token

        with (
            patch.object(token_auth_cache, "invalidate_team_tokens", side_effect=ConnectionError("redis down")),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.team.reset_token_and_save(user=self.user, is_impersonated_session=False)

        mock_auth_retry.assert_called_once_with(args=[self.team.id], countdown=5)
        mock_clear.assert_called_once_with(old_token)

    @override_settings(FLAGS_REDIS_URL="")
    @patch("posthog.tasks.team_metadata.clear_team_metadata_cache_for_token_task.delay")
    @patch("posthog.tasks.integrations.push_vercel_secrets.delay")
    def test_token_reset_without_flags_redis_does_not_enqueue_the_clear(
        self, _mock_push_vercel: Mock, mock_clear: Mock
    ) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self.team.reset_token_and_save(user=self.user, is_impersonated_session=False)

        mock_clear.assert_not_called()


@override_settings(FLAGS_REDIS_URL="redis://localhost:6379")
class TestFlagPolicyBlocklistCacheRefresh(BaseTest):
    @parameterized.expand(
        [
            ("create_with_entries", None, {"blocked_hosts": ["example.com"]}),
            ("set_on_existing_row", {}, {"blocked_hosts": ["example.com"], "blocked_ips": ["203.0.113.7"]}),
            (
                "clear_on_existing_row",
                {"blocked_hosts": ["example.com"], "blocked_ips": ["203.0.113.7"]},
                {"blocked_hosts": [], "blocked_ips": []},
            ),
        ]
    )
    def test_blocklist_save_refreshes_team_metadata_cache(
        self, _name: str, existing: dict[str, list[str]] | None, saved: dict[str, list[str]]
    ) -> None:
        config = None if existing is None else TeamFeatureFlagPolicyConfig.objects.create(team=self.team, **existing)

        with patch("posthog.tasks.team_metadata.update_team_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                if config is None:
                    TeamFeatureFlagPolicyConfig.objects.create(team=self.team, **saved)
                else:
                    for field, value in saved.items():
                        setattr(config, field, value)
                    config.save()

        mock_task.delay.assert_called_once_with(self.team.id)

    def test_creating_empty_flag_policy_does_not_refresh(self) -> None:
        with patch("posthog.tasks.team_metadata.update_team_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                TeamFeatureFlagPolicyConfig.objects.create(team=self.team)

        mock_task.delay.assert_not_called()

    def test_flag_policy_save_with_update_fields_outside_blocklist_does_not_refresh(self) -> None:
        config = TeamFeatureFlagPolicyConfig.objects.create(team=self.team, blocked_hosts=["example.com"])

        with patch("posthog.tasks.team_metadata.update_team_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                config.require_tags = True
                config.save(update_fields=["require_tags"])

        mock_task.delay.assert_not_called()
