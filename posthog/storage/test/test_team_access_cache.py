import json

from unittest.mock import patch

from django.test import TestCase, override_settings

import redis as redis_lib
from parameterized import parameterized

from posthog.storage.team_access_cache import TOKEN_CACHE_PREFIX, TokenAuthCache

# TTL for test cache entries (matches Python-side DEFAULT_CACHE_TTL in hypercache.py;
# Rust side is configurable via AUTH_TOKEN_CACHE_TTL_SECONDS, starting at 5 minutes).
DEFAULT_CACHE_TTL = 30 * 24 * 60 * 60


@override_settings(FLAGS_REDIS_URL=None)
class TestTokenAuthCacheNotConfigured(TestCase):
    """When FLAGS_REDIS_URL is None and no explicit client is provided, all invalidation is silently skipped."""

    def setUp(self):
        self.cache = TokenAuthCache()

    def test_invalidate_token_skips_when_not_configured(self):
        self.cache.invalidate_token("sha256$abc123")

    def test_invalidate_tokens_skips_when_not_configured(self):
        self.cache.invalidate_tokens(["sha256$abc123", "sha256$def456"])

    @patch("posthog.storage.team_access_cache.PersonalAPIKey")
    def test_invalidate_user_tokens_skips_db_query_when_not_configured(self, mock_pak):
        self.cache.invalidate_user_tokens(42)
        mock_pak.objects.filter.assert_not_called()

    def test_invalidate_team_tokens_skips_when_not_configured(self):
        counts = self.cache.invalidate_team_tokens(team_id=99999)
        assert counts == {"secret_tokens": 0, "project_secret_keys": 0, "personal_keys": 0, "total": 0}


class TestTokenAuthCache(TestCase):
    BATCH_TOKEN_HASHES = ["sha256$token_a", "sha256$token_b", "sha256$token_c"]

    def setUp(self):
        from posthog.redis import get_client

        self.redis: redis_lib.Redis = get_client()
        self.cache = TokenAuthCache(redis_client=self.redis)

        # Test data
        self.token_hash = "sha256$abc123def456"
        self.user_id = 42
        self.team_id = 7

        # Clean up any leftover test keys
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        from posthog.models.utils import hash_key_value

        # Delete the fixed token cache keys used across all tests in this class.
        # Avoid broad scan patterns — fakeredis is a process-wide singleton and a broad scan
        # would silently wipe keys from concurrently running tests.
        # Keys must be computed the same way the tests do (via hash_key_value), not as literals.
        raw_tokens = [
            "test_user_token_1",
            "test_user_token_2",
            "test_user_token_3",
            "test_my_token",
            "test_other_token",
            "test_fallback_key",
            "test_psak_token",
            "test_pak_include_token",
            "test_pak_scoped_token",
        ]
        keys_to_delete = [
            f"{TOKEN_CACHE_PREFIX}{self.token_hash}",
            *[f"{TOKEN_CACHE_PREFIX}{hash_key_value(raw)}" for raw in raw_tokens],
            *[f"{TOKEN_CACHE_PREFIX}{h}" for h in self.BATCH_TOKEN_HASHES],
        ]
        self.redis.delete(*keys_to_delete)

    def _seed_token_cache(self, token_hash: str, data: dict):
        cache_key = f"{TOKEN_CACHE_PREFIX}{token_hash}"
        self.redis.setex(cache_key, DEFAULT_CACHE_TTL, json.dumps(data))

    def test_invalidate_token_deletes_cache_entry(self):
        self._seed_token_cache(self.token_hash, {"type": "secret", "team_id": self.team_id})

        assert self.redis.exists(f"{TOKEN_CACHE_PREFIX}{self.token_hash}")

        self.cache.invalidate_token(self.token_hash)

        assert not self.redis.exists(f"{TOKEN_CACHE_PREFIX}{self.token_hash}")

    def test_invalidate_token_noop_when_no_cache_entry(self):
        # Should not raise
        self.cache.invalidate_token("sha256$nonexistent")

    def test_invalidate_user_tokens_deletes_all_user_entries(self):
        from posthog.models.personal_api_key import PersonalAPIKey
        from posthog.models.user import User
        from posthog.models.utils import hash_key_value

        user = User.objects.create(email="cache_bulk_test@example.com", is_active=True)
        raw_keys = ["test_user_token_1", "test_user_token_2", "test_user_token_3"]
        token_hashes = []
        for raw in raw_keys:
            secure_value = hash_key_value(raw)
            PersonalAPIKey.objects.create(user=user, label=f"Key {raw}", secure_value=secure_value)
            token_hashes.append(secure_value)
            self._seed_token_cache(secure_value, {"type": "personal", "user_id": user.id})

        for token in token_hashes:
            assert self.redis.exists(f"{TOKEN_CACHE_PREFIX}{token}")

        self.cache.invalidate_user_tokens(user.id)

        for token in token_hashes:
            assert not self.redis.exists(f"{TOKEN_CACHE_PREFIX}{token}")

    def test_invalidate_user_tokens_uses_db(self):
        from posthog.models.personal_api_key import PersonalAPIKey
        from posthog.models.user import User
        from posthog.models.utils import hash_key_value

        user = User.objects.create(email="cache_test@example.com", is_active=True)
        secure_value = hash_key_value("test_fallback_key")
        PersonalAPIKey.objects.create(
            user=user,
            label="DB Test Key",
            secure_value=secure_value,
        )

        self.redis.setex(f"{TOKEN_CACHE_PREFIX}{secure_value}", DEFAULT_CACHE_TTL, json.dumps({"type": "personal"}))

        self.cache.invalidate_user_tokens(user.id)

        assert not self.redis.exists(f"{TOKEN_CACHE_PREFIX}{secure_value}")

    def test_invalidate_user_tokens_noop_for_legacy_pbkdf2_only_keys(self):
        from unittest.mock import patch

        from posthog.models.personal_api_key import PersonalAPIKey
        from posthog.models.user import User

        user = User.objects.create(email="pbkdf2_only_user@example.com", is_active=True)
        # PBKDF2-format key — Rust never caches these under this hash, so nothing to invalidate
        PersonalAPIKey.objects.create(
            user=user,
            label="Legacy Key",
            secure_value="pbkdf2_sha256$260000$somesalt$hashvalue123",
        )

        with patch.object(self.redis, "delete") as mock_delete:
            self.cache.invalidate_user_tokens(user.id)
            mock_delete.assert_not_called()

    def test_invalidate_tokens_deletes_multiple_entries(self):
        for h in self.BATCH_TOKEN_HASHES:
            self._seed_token_cache(h, {"type": "test"})

        self.cache.invalidate_tokens(self.BATCH_TOKEN_HASHES)

        for h in self.BATCH_TOKEN_HASHES:
            assert not self.redis.exists(f"{TOKEN_CACHE_PREFIX}{h}")

    def test_invalidate_tokens_noop_on_empty_list(self):
        self.cache.invalidate_tokens([])  # should not raise

    def test_invalidate_team_tokens_deletes_secret_tokens(self):
        from posthog.models.team.team import Team
        from posthog.models.utils import generate_random_token_secret, hash_key_value

        team = Team.objects.create(
            organization=self._get_or_create_org(),
            name="Secret Token Test Team",
            secret_api_token=generate_random_token_secret(),
            secret_api_token_backup=generate_random_token_secret(),
        )
        primary_hash = hash_key_value(team.secret_api_token, mode="sha256")
        backup_hash = hash_key_value(team.secret_api_token_backup, mode="sha256")
        self._seed_token_cache(primary_hash, {"type": "secret", "team_id": team.id})
        self._seed_token_cache(backup_hash, {"type": "secret", "team_id": team.id})

        counts = self.cache.invalidate_team_tokens(team.id)

        assert counts["secret_tokens"] == 2
        assert not self.redis.exists(f"{TOKEN_CACHE_PREFIX}{primary_hash}")
        assert not self.redis.exists(f"{TOKEN_CACHE_PREFIX}{backup_hash}")

    def test_invalidate_team_tokens_deletes_psak_entries(self):
        from posthog.models.project_secret_api_key import ProjectSecretAPIKey
        from posthog.models.team.team import Team
        from posthog.models.utils import generate_random_token_secret, hash_key_value

        team = Team.objects.create(
            organization=self._get_or_create_org(),
            name="PSAK Test Team",
            secret_api_token=generate_random_token_secret(),
        )
        psak = ProjectSecretAPIKey.objects.create(
            team=team,
            label="Test PSAK",
            secure_value=hash_key_value("test_psak_token"),
        )
        assert psak.secure_value is not None
        self._seed_token_cache(psak.secure_value, {"type": "project_secret", "team_id": team.id})

        counts = self.cache.invalidate_team_tokens(team.id)

        assert counts["project_secret_keys"] == 1
        assert not self.redis.exists(f"{TOKEN_CACHE_PREFIX}{psak.secure_value}")

    def test_invalidate_team_tokens_includes_personal_keys(self):
        from posthog.models.personal_api_key import PersonalAPIKey
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_secret, hash_key_value

        org = self._get_or_create_org()
        team = Team.objects.create(
            organization=org, name="PAK Include Test Team", secret_api_token=generate_random_token_secret()
        )
        user = User.objects.create(email="pak_include_test@example.com", is_active=True)
        user.join(organization=org)

        pak_hash = hash_key_value("test_pak_include_token")
        PersonalAPIKey.objects.create(user=user, label="Include Key", secure_value=pak_hash)
        self._seed_token_cache(pak_hash, {"type": "personal", "user_id": user.id})

        counts = self.cache.invalidate_team_tokens(team.id)

        assert counts["personal_keys"] == 1
        assert not self.redis.exists(f"{TOKEN_CACHE_PREFIX}{pak_hash}")

    @parameterized.expand(
        [
            ("scoped_to_different_team", "other_team", None, 0),
            ("scoped_to_different_org", None, "other_org", 0),
            ("scoped_to_target_team", "target_team", None, 1),
            ("empty_scope_arrays", [], [], 1),
        ]
    )
    def test_invalidate_team_tokens_pak_scoping(self, _name, scoped_teams, scoped_organizations, expected_count):
        from posthog.models.organization import Organization
        from posthog.models.personal_api_key import PersonalAPIKey
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_secret, hash_key_value

        org = self._get_or_create_org()
        team = Team.objects.create(
            organization=org, name="PAK Scope Test", secret_api_token=generate_random_token_secret()
        )
        user = User.objects.create(email="pak_scope_test@example.com", is_active=True)
        user.join(organization=org)

        # Resolve sentinel values to real IDs
        if scoped_teams == "other_team":
            other_team = Team.objects.create(
                organization=org, name="Other Team", secret_api_token=generate_random_token_secret()
            )
            scoped_teams = [other_team.id]
        elif scoped_teams == "target_team":
            scoped_teams = [team.id]

        if scoped_organizations == "other_org":
            other_org = Organization.objects.create(name="Other Org")
            scoped_organizations = [str(other_org.id)]

        pak_hash = hash_key_value("test_pak_scoped_token")
        pak_kwargs: dict = {"user": user, "label": "Scoped Key", "secure_value": pak_hash}
        if scoped_teams is not None:
            pak_kwargs["scoped_teams"] = scoped_teams
        if scoped_organizations is not None:
            pak_kwargs["scoped_organizations"] = scoped_organizations
        PersonalAPIKey.objects.create(**pak_kwargs)
        self._seed_token_cache(pak_hash, {"type": "personal", "user_id": user.id})

        counts = self.cache.invalidate_team_tokens(team.id)

        assert counts["personal_keys"] == expected_count
        should_exist = expected_count == 0
        assert self.redis.exists(f"{TOKEN_CACHE_PREFIX}{pak_hash}") == should_exist

    def _get_or_create_org(self):
        from posthog.models.organization import Organization

        return Organization.objects.get_or_create(name="Test Org for Auth Cache")[0]

    def test_invalidate_preserves_other_users_tokens(self):
        from posthog.models.personal_api_key import PersonalAPIKey
        from posthog.models.user import User
        from posthog.models.utils import hash_key_value

        user1 = User.objects.create(email="cache_user1@example.com", is_active=True)
        user2 = User.objects.create(email="cache_user2@example.com", is_active=True)

        my_secure_value = hash_key_value("test_my_token")
        other_secure_value = hash_key_value("test_other_token")

        PersonalAPIKey.objects.create(user=user1, label="User1 Key", secure_value=my_secure_value)
        PersonalAPIKey.objects.create(user=user2, label="User2 Key", secure_value=other_secure_value)

        self._seed_token_cache(my_secure_value, {"type": "personal", "user_id": user1.id})
        self._seed_token_cache(other_secure_value, {"type": "personal", "user_id": user2.id})

        self.cache.invalidate_user_tokens(user1.id)

        # User1's token should be gone
        assert not self.redis.exists(f"{TOKEN_CACHE_PREFIX}{my_secure_value}")
        # User2's token should be untouched
        assert self.redis.exists(f"{TOKEN_CACHE_PREFIX}{other_secure_value}")
