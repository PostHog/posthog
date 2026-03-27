import json

from unittest.mock import patch

from django.test import TestCase

import redis as redis_lib

from posthog.models.organization import Organization
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.storage.auth_token_cache_verifier import verify_and_fix_auth_token_cache
from posthog.storage.team_access_cache import TOKEN_CACHE_PREFIX


class TestAuthTokenCacheVerifier(TestCase):
    def setUp(self):
        from posthog.redis import get_client

        self.redis: redis_lib.Redis = get_client()
        self.org = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(
            organization=self.org,
            name="Test Team",
            api_token="phc_test_verifier_token",
            secret_api_token="phs_test_secret_token",
        )
        self.user = User.objects.create_and_join(
            organization=self.org,
            email="verifier@test.com",
            password="test1234",
        )
        self._cleanup_keys: list[str] = []

    def tearDown(self):
        if self._cleanup_keys:
            self.redis.delete(*self._cleanup_keys)

    def _set_cache(self, token_hash: str | None, data: dict, ttl: int = 3600) -> str:
        assert token_hash is not None, "token_hash must not be None in test setup"
        key = f"{TOKEN_CACHE_PREFIX}{token_hash}"
        self.redis.setex(key, ttl, json.dumps(data))
        self._cleanup_keys.append(key)
        return key

    # --- Empty scan ---

    def test_empty_scan_returns_zero_results(self):
        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)
        # We can't assert total_scanned == 0 because other tests may leave keys,
        # but verify_and_fix should complete without error and report no issues
        assert result.stale_found == 0
        assert result.parse_errors == 0
        assert result.db_errors == 0

    # --- Secret token verification ---

    def test_valid_secret_token_is_kept(self):
        token_hash = hash_key_value(self.team.secret_api_token, mode="sha256")
        key = self._set_cache(token_hash, {"type": "secret", "team_id": self.team.id})

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert self.redis.exists(key)
        assert result.valid >= 1

    def test_secret_token_for_deleted_team_is_removed(self):
        deleted_team = Team.objects.create(
            organization=self.org,
            name="Deleted Team",
            api_token="phc_deleted_team",
            secret_api_token="phs_deleted_secret",
        )
        token_hash = hash_key_value("phs_deleted_secret", mode="sha256")
        key = self._set_cache(token_hash, {"type": "secret", "team_id": deleted_team.id})

        # Delete the team (but keep the cache entry)
        deleted_team.delete()

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)
        assert result.stale_found > 0

    def test_secret_token_with_rotated_hash_is_removed(self):
        # Cache entry has the right team_id but the hash no longer matches any token
        fake_hash = hash_key_value("phs_old_rotated_token", mode="sha256")
        key = self._set_cache(fake_hash, {"type": "secret", "team_id": self.team.id})

        verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)

    def test_secret_token_backup_is_valid(self):
        self.team.secret_api_token_backup = "phs_backup_token"
        self.team.save(update_fields=["secret_api_token_backup"])

        token_hash = hash_key_value("phs_backup_token", mode="sha256")
        key = self._set_cache(token_hash, {"type": "secret", "team_id": self.team.id})

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert self.redis.exists(key)
        assert result.valid >= 1

    # --- Personal token verification ---

    def test_valid_personal_token_is_kept(self):
        pak = PersonalAPIKey.objects.create(
            user=self.user,
            label="test-pak-valid",
            secure_value=hash_key_value("phx_pak_valid", mode="sha256"),
            scopes=["feature_flag:read"],
        )

        org_ids = [str(self.org.id)]
        key = self._set_cache(
            pak.secure_value,
            {
                "type": "personal",
                "user_id": self.user.id,
                "key_id": str(pak.id),
                "org_ids": org_ids,
                "scoped_teams": None,
                "scoped_orgs": None,
                "scopes": ["feature_flag:read"],
            },
        )

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert self.redis.exists(key)
        assert result.valid >= 1

    def test_personal_token_for_deleted_key_is_removed(self):
        fake_sv = hash_key_value("phx_pak_deleted", mode="sha256")
        key = self._set_cache(
            fake_sv,
            {
                "type": "personal",
                "user_id": self.user.id,
                "key_id": "nonexistent",
                "org_ids": [str(self.org.id)],
                "scoped_teams": None,
                "scoped_orgs": None,
                "scopes": ["feature_flag:read"],
            },
        )

        verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)

    def test_personal_token_for_deactivated_user_is_removed(self):
        inactive_user = User.objects.create_and_join(
            organization=self.org,
            email="inactive@test.com",
            password="test1234",
        )
        pak = PersonalAPIKey.objects.create(
            user=inactive_user,
            label="test-pak-inactive",
            secure_value=hash_key_value("phx_pak_inactive", mode="sha256"),
            scopes=["feature_flag:read"],
        )
        inactive_user.is_active = False
        inactive_user.save(update_fields=["is_active"])

        key = self._set_cache(
            pak.secure_value,
            {
                "type": "personal",
                "user_id": inactive_user.id,
                "key_id": str(pak.id),
                "org_ids": [str(self.org.id)],
                "scoped_teams": None,
                "scoped_orgs": None,
                "scopes": ["feature_flag:read"],
            },
        )

        verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)

    def test_personal_token_with_changed_org_membership_is_removed(self):
        pak = PersonalAPIKey.objects.create(
            user=self.user,
            label="test-pak-org-change",
            secure_value=hash_key_value("phx_pak_org_change", mode="sha256"),
            scopes=["feature_flag:read"],
        )

        # Cache has a stale org that the user no longer belongs to
        key = self._set_cache(
            pak.secure_value,
            {
                "type": "personal",
                "user_id": self.user.id,
                "key_id": str(pak.id),
                "org_ids": [str(self.org.id), "stale-org-uuid"],
                "scoped_teams": None,
                "scoped_orgs": None,
                "scopes": ["feature_flag:read"],
            },
        )

        verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)

    def test_personal_token_with_changed_scopes_is_removed(self):
        pak = PersonalAPIKey.objects.create(
            user=self.user,
            label="test-pak-scope-change",
            secure_value=hash_key_value("phx_pak_scope_change", mode="sha256"),
            scopes=["feature_flag:write"],
        )

        # Cache has old scopes
        key = self._set_cache(
            pak.secure_value,
            {
                "type": "personal",
                "user_id": self.user.id,
                "key_id": str(pak.id),
                "org_ids": [str(self.org.id)],
                "scoped_teams": None,
                "scoped_orgs": None,
                "scopes": ["feature_flag:read"],
            },
        )

        verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)

    def test_personal_token_with_changed_scoped_teams_is_removed(self):
        pak = PersonalAPIKey.objects.create(
            user=self.user,
            label="test-pak-scoped-teams",
            secure_value=hash_key_value("phx_pak_scoped_teams", mode="sha256"),
            scopes=["feature_flag:read"],
            scoped_teams=[self.team.id],
        )

        # Cache has stale scoped_teams
        key = self._set_cache(
            pak.secure_value,
            {
                "type": "personal",
                "user_id": self.user.id,
                "key_id": str(pak.id),
                "org_ids": [str(self.org.id)],
                "scoped_teams": [self.team.id, 99999],
                "scoped_orgs": None,
                "scopes": ["feature_flag:read"],
            },
        )

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)
        assert result.stale_found > 0

    def test_personal_token_with_changed_scoped_orgs_is_removed(self):
        pak = PersonalAPIKey.objects.create(
            user=self.user,
            label="test-pak-scoped-orgs",
            secure_value=hash_key_value("phx_pak_scoped_orgs", mode="sha256"),
            scopes=["feature_flag:read"],
            scoped_organizations=[str(self.org.id)],
        )

        # Cache has stale scoped_orgs (Rust field name for scoped_organizations)
        key = self._set_cache(
            pak.secure_value,
            {
                "type": "personal",
                "user_id": self.user.id,
                "key_id": str(pak.id),
                "org_ids": [str(self.org.id)],
                "scoped_teams": None,
                "scoped_orgs": [str(self.org.id), "stale-org-uuid"],
                "scopes": ["feature_flag:read"],
            },
        )

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)
        assert result.stale_found > 0

    def test_personal_token_with_null_org_ids_is_removed(self):
        pak = PersonalAPIKey.objects.create(
            user=self.user,
            label="test-pak-null-org-ids",
            secure_value=hash_key_value("phx_pak_null_org_ids", mode="sha256"),
            scopes=["feature_flag:read"],
        )

        # Cache has org_ids explicitly set to null (malformed entry)
        key = self._set_cache(
            pak.secure_value,
            {
                "type": "personal",
                "user_id": self.user.id,
                "key_id": str(pak.id),
                "org_ids": None,
                "scoped_teams": None,
                "scoped_orgs": None,
                "scopes": ["feature_flag:read"],
            },
        )

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)
        assert result.stale_found > 0
        assert result.parse_errors > 0

    # --- Project secret token verification ---

    def test_valid_project_secret_token_is_kept(self):
        psak = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="test-psak-valid",
            secure_value=hash_key_value("phx_psak_valid", mode="sha256"),
            scopes=["feature_flag:read"],
            mask_value="phx_...vald",
        )

        key = self._set_cache(
            psak.secure_value,
            {
                "type": "project_secret",
                "team_id": self.team.id,
                "key_id": str(psak.id),
                "scopes": ["feature_flag:read"],
            },
        )

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert self.redis.exists(key)
        assert result.valid >= 1

    def test_project_secret_token_for_deleted_key_is_removed(self):
        fake_sv = hash_key_value("phx_psak_deleted", mode="sha256")
        key = self._set_cache(
            fake_sv,
            {
                "type": "project_secret",
                "team_id": self.team.id,
                "key_id": "nonexistent",
                "scopes": ["feature_flag:read"],
            },
        )

        verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)

    def test_project_secret_token_with_wrong_team_id_is_removed(self):
        psak = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="test-psak-team-id",
            secure_value=hash_key_value("phx_psak_team_id", mode="sha256"),
            scopes=["feature_flag:read"],
            mask_value="phx_...tmid",
        )

        # Cache has a wrong team_id
        key = self._set_cache(
            psak.secure_value,
            {
                "type": "project_secret",
                "team_id": 99999,
                "key_id": str(psak.id),
                "scopes": ["feature_flag:read"],
            },
        )

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)
        assert result.stale_found > 0

    def test_project_secret_token_with_wrong_key_id_is_removed(self):
        psak = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="test-psak-key-id",
            secure_value=hash_key_value("phx_psak_key_id", mode="sha256"),
            scopes=["feature_flag:read"],
            mask_value="phx_...kyid",
        )

        # Cache has a wrong key_id
        key = self._set_cache(
            psak.secure_value,
            {
                "type": "project_secret",
                "team_id": self.team.id,
                "key_id": "wrong-key-id",
                "scopes": ["feature_flag:read"],
            },
        )

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)
        assert result.stale_found > 0

    def test_project_secret_token_with_changed_scopes_is_removed(self):
        psak = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="test-psak-scope-change",
            secure_value=hash_key_value("phx_psak_scope_change", mode="sha256"),
            scopes=["feature_flag:write"],
            mask_value="phx_...scop",
        )

        # Cache has old scopes
        key = self._set_cache(
            psak.secure_value,
            {
                "type": "project_secret",
                "team_id": self.team.id,
                "key_id": str(psak.id),
                "scopes": ["feature_flag:read"],
            },
        )

        verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)

    # --- Project secret token missing mandatory fields ---

    def test_project_secret_token_missing_team_id_is_removed(self):
        psak = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="test-psak-no-team-id",
            secure_value=hash_key_value("phx_psak_no_team_id", mode="sha256"),
            scopes=["feature_flag:read"],
            mask_value="phx_...ntid",
        )

        key = self._set_cache(
            psak.secure_value,
            {
                "type": "project_secret",
                # intentionally omitting "team_id" — Rust always writes this
                "key_id": str(psak.id),
                "scopes": ["feature_flag:read"],
            },
        )

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)
        assert result.stale_found > 0

    def test_project_secret_token_missing_key_id_is_removed(self):
        psak = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="test-psak-no-key-id",
            secure_value=hash_key_value("phx_psak_no_key_id", mode="sha256"),
            scopes=["feature_flag:read"],
            mask_value="phx_...nkid",
        )

        key = self._set_cache(
            psak.secure_value,
            {
                "type": "project_secret",
                "team_id": self.team.id,
                # intentionally omitting "key_id" — Rust always writes this
                "scopes": ["feature_flag:read"],
            },
        )

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)
        assert result.stale_found > 0

    # --- Edge cases ---

    def test_unknown_token_type_is_removed(self):
        key = self._set_cache(
            "sha256$unknown_type_token",
            {
                "type": "unknown_future_type",
                "data": "something",
            },
        )

        verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)

    def test_malformed_json_is_removed(self):
        key = f"{TOKEN_CACHE_PREFIX}sha256$malformed_json"
        self.redis.setex(key, 3600, "not valid json {{{")
        self._cleanup_keys.append(key)

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)
        assert result.parse_errors > 0

    def test_non_dict_json_is_removed(self):
        key = f"{TOKEN_CACHE_PREFIX}sha256$non_dict_json"
        self.redis.setex(key, 3600, "[1, 2, 3]")
        self._cleanup_keys.append(key)

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)
        assert result.parse_errors > 0

    # --- Secret token missing team_id ---

    def test_secret_token_missing_team_id_is_removed(self):
        key = self._set_cache(
            "sha256$secret_no_team_id",
            {"type": "secret"},  # no "team_id" field
        )

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)
        assert result.stale_found > 0
        assert result.stale_by_type["secret"] > 0

    # --- Non-list org_ids for personal token ---

    def test_personal_token_with_string_org_ids_is_removed(self):
        pak = PersonalAPIKey.objects.create(
            user=self.user,
            label="test-pak-string-org-ids",
            secure_value=hash_key_value("phx_pak_string_org_ids", mode="sha256"),
            scopes=["feature_flag:read"],
        )

        key = self._set_cache(
            pak.secure_value,
            {
                "type": "personal",
                "user_id": self.user.id,
                "key_id": str(pak.id),
                "org_ids": "not-a-list",  # string instead of list
                "scoped_teams": None,
                "scoped_orgs": None,
                "scopes": ["feature_flag:read"],
            },
        )

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)
        assert result.parse_errors > 0

    # --- DB error paths ---

    def test_secret_entry_db_error_is_counted(self):
        token_hash = hash_key_value(self.team.secret_api_token, mode="sha256")
        key = self._set_cache(token_hash, {"type": "secret", "team_id": self.team.id})

        with patch.object(Team.objects, "filter", side_effect=Exception("DB down")):
            result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert result.db_errors >= 1
        # Must NOT delete the entry on a DB error
        assert self.redis.exists(key)

    def test_personal_entry_db_error_is_counted(self):
        pak = PersonalAPIKey.objects.create(
            user=self.user,
            label="test-pak-db-error",
            secure_value=hash_key_value("phx_pak_db_error", mode="sha256"),
            scopes=["feature_flag:read"],
        )

        key = self._set_cache(
            pak.secure_value,
            {
                "type": "personal",
                "user_id": self.user.id,
                "key_id": str(pak.id),
                "org_ids": [str(self.org.id)],
                "scoped_teams": None,
                "scoped_orgs": None,
                "scopes": ["feature_flag:read"],
            },
        )

        with patch.object(PersonalAPIKey.objects, "filter", side_effect=Exception("DB down")):
            result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert result.db_errors >= 1
        assert self.redis.exists(key)

    def test_project_secret_entry_db_error_is_counted(self):
        psak = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="test-psak-db-error",
            secure_value=hash_key_value("phx_psak_db_error", mode="sha256"),
            scopes=["feature_flag:read"],
            mask_value="phx_...dber",
        )

        key = self._set_cache(
            psak.secure_value,
            {
                "type": "project_secret",
                "team_id": self.team.id,
                "key_id": str(psak.id),
                "scopes": ["feature_flag:read"],
            },
        )

        with patch.object(ProjectSecretAPIKey.objects, "filter", side_effect=Exception("DB down")):
            result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert result.db_errors >= 1
        assert self.redis.exists(key)

    # --- Redis delete error ---

    def test_redis_delete_error_increments_delete_errors(self):
        # Insert a stale entry (team_id that doesn't exist)
        self._set_cache(
            "sha256$stale_for_delete_error",
            {"type": "secret", "team_id": 999999999},
        )

        with patch.object(self.redis, "delete", side_effect=Exception("Redis write timeout")):
            result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert result.stale_found >= 1
        assert result.delete_errors >= 1

    # --- Multi-batch processing ---

    def test_multi_batch_processes_all_entries(self):
        stale_keys = []
        for i in range(11):
            key = self._set_cache(
                f"sha256$multi_batch_stale_{i:02d}",
                {"type": "secret", "team_id": 9999900 + i},
            )
            stale_keys.append(key)

        valid_token_hash = hash_key_value(self.team.secret_api_token, mode="sha256")
        valid_key = self._set_cache(valid_token_hash, {"type": "secret", "team_id": self.team.id})

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert result.total_scanned >= 12
        for key in stale_keys:
            assert not self.redis.exists(key)
        assert self.redis.exists(valid_key)

    # --- Empty scopes equivalence with null cache scopes ---

    def test_personal_token_empty_scopes_matches_null_cache_scopes(self):
        pak = PersonalAPIKey.objects.create(
            user=self.user,
            label="test-pak-empty-scopes",
            secure_value=hash_key_value("phx_pak_empty_scopes", mode="sha256"),
            scopes=[],
        )

        key = self._set_cache(
            pak.secure_value,
            {
                "type": "personal",
                "user_id": self.user.id,
                "key_id": str(pak.id),
                "org_ids": [str(self.org.id)],
                "scoped_teams": None,
                "scoped_orgs": None,
                "scopes": None,  # null in cache, [] in DB — _normalize_optional_list treats both as None
            },
        )

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert self.redis.exists(key)
        assert result.valid >= 1

    # --- Key expiring between SCAN and MGET ---

    def test_key_expired_between_scan_and_mget_is_skipped_gracefully(self):
        self._set_cache(
            "sha256$expires_mid_flight",
            {"type": "secret", "team_id": self.team.id},
        )

        def mget_all_expired(keys):
            # Simulate every key having expired between SCAN and MGET
            return [None] * len(keys)

        with patch.object(self.redis, "mget", side_effect=mget_all_expired):
            result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert result.parse_errors == 0
        assert result.stale_found == 0

    # --- Personal token missing key_id field ---

    def test_personal_token_with_missing_key_id_is_removed(self):
        pak = PersonalAPIKey.objects.create(
            user=self.user,
            label="test-pak-no-key-id",
            secure_value=hash_key_value("phx_pak_no_key_id", mode="sha256"),
            scopes=["feature_flag:read"],
        )

        key = self._set_cache(
            pak.secure_value,
            {
                "type": "personal",
                "user_id": self.user.id,
                # intentionally omitting "key_id" to simulate an old Rust entry
                "org_ids": [str(self.org.id)],
                "scoped_teams": None,
                "scoped_orgs": None,
                "scopes": ["feature_flag:read"],
            },
        )

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)
        assert result.stale_found > 0

    # --- Personal token wrong key_id ---

    def test_personal_token_with_wrong_key_id_is_removed(self):
        pak = PersonalAPIKey.objects.create(
            user=self.user,
            label="test-pak-wrong-key-id",
            secure_value=hash_key_value("phx_pak_wrong_key_id", mode="sha256"),
            scopes=["feature_flag:read"],
        )

        key = self._set_cache(
            pak.secure_value,
            {
                "type": "personal",
                "user_id": self.user.id,
                "key_id": "99999999",  # wrong key_id — could corrupt last_used_at tracking
                "org_ids": [str(self.org.id)],
                "scoped_teams": None,
                "scoped_orgs": None,
                "scopes": ["feature_flag:read"],
            },
        )

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)
        assert result.stale_found > 0

    # --- Unknown token type increments parse_errors ---

    def test_unknown_token_type_increments_parse_errors(self):
        key = self._set_cache(
            "sha256$unknown_future_type_counters",
            {
                "type": "unknown_future_type",
                "data": "something",
            },
        )

        result = verify_and_fix_auth_token_cache(self.redis, batch_size=10)

        assert not self.redis.exists(key)
        assert result.parse_errors >= 1
        assert result.stale_found >= 1
