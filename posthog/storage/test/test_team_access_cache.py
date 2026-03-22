import json

from unittest.mock import patch

from django.test import TestCase, override_settings

import redis as redis_lib

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
        from posthog.models.personal_api_key import hash_key_value

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
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.user import User

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
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.user import User

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

    def test_invalidate_preserves_other_users_tokens(self):
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.user import User

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
