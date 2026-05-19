import json
from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

import redis as redis_lib
from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_secret
from posthog.storage.team_access_cache import TOKEN_CACHE_PREFIX, token_auth_cache

DEFAULT_CACHE_TTL = 300


class TestInvalidateFlagsAuthCacheCommand(BaseTest):
    def setUp(self):
        super().setUp()
        from posthog.redis import get_client

        self.redis: redis_lib.Redis = get_client()
        self.stdout = StringIO()
        self.stderr = StringIO()

        # Point the global token_auth_cache at the test Redis so seeded entries
        # and deletions use the same database.
        self._original_redis_client = token_auth_cache._redis_client
        token_auth_cache._redis_client = self.redis

        # BaseTest's team doesn't have secret tokens set
        self.team.secret_api_token = generate_random_token_secret()
        self.team.secret_api_token_backup = generate_random_token_secret()
        self.team.save(update_fields=["secret_api_token", "secret_api_token_backup"])

    def tearDown(self):
        token_auth_cache._redis_client = self._original_redis_client
        super().tearDown()

    def _seed_cache(self, token_hash: str, data: dict) -> None:
        self.redis.setex(f"{TOKEN_CACHE_PREFIX}{token_hash}", DEFAULT_CACHE_TTL, json.dumps(data))

    def _cache_exists(self, token_hash: str) -> bool:
        return bool(self.redis.exists(f"{TOKEN_CACHE_PREFIX}{token_hash}"))

    def _call(self, *args: str) -> str:
        self.stdout = StringIO()
        call_command("invalidate_flags_auth_cache", *args, stdout=self.stdout, stderr=self.stderr)
        return self.stdout.getvalue()

    def test_invalidates_team_secret_tokens(self):
        assert self.team.secret_api_token is not None
        assert self.team.secret_api_token_backup is not None
        primary_hash = hash_key_value(self.team.secret_api_token, mode="sha256")
        backup_hash = hash_key_value(self.team.secret_api_token_backup, mode="sha256")
        self._seed_cache(primary_hash, {"type": "secret", "team_id": self.team.id})
        self._seed_cache(backup_hash, {"type": "secret", "team_id": self.team.id})

        output = self._call("--team-id", str(self.team.id))

        assert not self._cache_exists(primary_hash)
        assert not self._cache_exists(backup_hash)
        assert "Secret tokens:       2" in output

    def test_invalidates_psaks(self):
        psak = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="Test PSAK",
            secure_value=hash_key_value("test_cmd_psak"),
        )
        assert psak.secure_value is not None
        self._seed_cache(psak.secure_value, {"type": "project_secret", "team_id": self.team.id})

        output = self._call("--team-id", str(self.team.id))

        assert not self._cache_exists(psak.secure_value)
        assert "Project secret keys: 1" in output

    def test_invalidates_personal_keys(self):
        pak_hash = hash_key_value("test_cmd_pak")
        PersonalAPIKey.objects.create(user=self.user, label="Test PAK", secure_value=pak_hash)
        self._seed_cache(pak_hash, {"type": "personal", "user_id": self.user.id})

        output = self._call("--team-id", str(self.team.id))

        assert not self._cache_exists(pak_hash)
        assert "Personal keys:       1" in output

    @parameterized.expand(
        [
            ("scoped_to_different_team", "other_team", None),
            ("scoped_to_different_org", None, "other_org"),
        ]
    )
    def test_skips_pak_scoped_to_different(self, _name, scope_team, scope_org):
        pak_hash = hash_key_value("test_cmd_pak_scoped")
        pak_kwargs: dict = {"user": self.user, "label": "Scoped PAK", "secure_value": pak_hash}

        if scope_team == "other_team":
            other_team = Team.objects.create(organization=self.organization, name="Other Team")
            pak_kwargs["scoped_teams"] = [other_team.id]

        if scope_org == "other_org":
            other_org = Organization.objects.create(name="Other Org")
            pak_kwargs["scoped_organizations"] = [str(other_org.id)]

        PersonalAPIKey.objects.create(**pak_kwargs)
        self._seed_cache(pak_hash, {"type": "personal", "user_id": self.user.id})

        output = self._call("--team-id", str(self.team.id))

        assert self._cache_exists(pak_hash)
        assert "Personal keys:       0" in output

    def test_dry_run_does_not_delete(self):
        assert self.team.secret_api_token is not None
        primary_hash = hash_key_value(self.team.secret_api_token, mode="sha256")
        self._seed_cache(primary_hash, {"type": "secret", "team_id": self.team.id})

        output = self._call("--team-id", str(self.team.id), "--dry-run")

        assert self._cache_exists(primary_hash)
        assert "DRY RUN" in output
        assert "No entries were deleted" in output

    def test_nonexistent_team_raises_error(self):
        with self.assertRaises(CommandError) as cm:
            self._call("--team-id", "999999")
        assert "Team 999999 not found" in str(cm.exception)

    @override_settings(FLAGS_REDIS_URL=None)
    def test_not_configured_raises_error(self):
        # Temporarily clear the injected client so is_configured checks the setting
        token_auth_cache._redis_client = None
        try:
            with self.assertRaises(CommandError) as cm:
                self._call("--team-id", str(self.team.id))
            assert "FLAGS_REDIS_URL is not configured" in str(cm.exception)
        finally:
            token_auth_cache._redis_client = self.redis

    @override_settings(FLAGS_REDIS_URL=None)
    def test_dry_run_works_without_redis(self):
        # Temporarily clear the injected client so is_configured checks the setting
        token_auth_cache._redis_client = None
        try:
            output = self._call("--team-id", str(self.team.id), "--dry-run")
            assert "DRY RUN" in output
            assert "No entries were deleted" in output
        finally:
            token_auth_cache._redis_client = self.redis

    def test_dry_run_counts_match_actual_invalidation(self):
        psak = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="Count Test PSAK",
            secure_value=hash_key_value("test_cmd_count_psak"),
        )
        assert psak.secure_value is not None
        self._seed_cache(psak.secure_value, {"type": "project_secret", "team_id": self.team.id})

        pak_hash = hash_key_value("test_cmd_count_pak")
        PersonalAPIKey.objects.create(user=self.user, label="Count PAK", secure_value=pak_hash)
        self._seed_cache(pak_hash, {"type": "personal", "user_id": self.user.id})

        args = ["--team-id", str(self.team.id)]

        dry_output = self._call(*args, "--dry-run")
        actual_output = self._call(*args)

        # Extract total lines
        dry_total = next(line for line in dry_output.splitlines() if "Total" in line)
        actual_total = next(line for line in actual_output.splitlines() if "Total" in line)

        # Both should report the same count
        dry_count = int(dry_total.split()[-1])
        actual_count = int(actual_total.split()[-1])
        assert dry_count == actual_count
