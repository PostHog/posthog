import json
from datetime import timedelta
from decimal import Decimal

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.conf import settings
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import SHA256_HASH_PREFIX, generate_random_token, generate_random_token_secret, hash_key_value
from posthog.redis import get_client
from posthog.settings.utils import generate_rsa_private_key_pem
from posthog.storage.gateway_credential_cache import (
    GATEWAY_CREDENTIAL_FIELDS,
    GATEWAY_CREDENTIAL_LAST_USED_KEY,
    GATEWAY_CREDENTIAL_SECRET_KEY_CACHE_TTL,
    OVERSPEND_ALLOWANCE_KEY,
    clear_gateway_credential,
    credential_hash,
    drain_gateway_credential_last_used,
    format_overspend_allowance_usd,
    gateway_credential_hypercache as hypercache,
    project_gateway_credential,
    refresh_all_gateway_credentials,
    validate_overspend_allowance_usd,
)
from posthog.tasks.gateway_credential import (
    drain_gateway_credential_last_used_task,
    refresh_gateway_credentials,
    reproject_team_gateway_credentials_task,
    reproject_user_gateway_credentials_task,
    update_gateway_credential_cache_task,
)

_TEST_GATEWAY_REDIS_URL = "redis://localhost:6379/15"

GATEWAY_SCOPE = "llm_gateway:read"
SECRET_KEY_KIND = "project_secret_api_key"


@override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": generate_rsa_private_key_pem()})
class GatewayCredentialTestMixin(BaseTest):
    def setUp(self):
        super().setUp()
        # LocMemCache persists across tests in-process; isolate each test.
        hypercache.cache_client.clear()

    def _make_secret_key(self, scopes: list[str], token: str | None = None) -> tuple[ProjectSecretAPIKey, str]:
        token = token or generate_random_token_secret()
        key = ProjectSecretAPIKey.objects.create(
            label=f"sk {token[-12:]}",  # unique_team_label requires a distinct label per team
            team=self.team,
            secure_value=hash_key_value(token),
            scopes=scopes,
        )
        return key, token

    def _make_oauth(
        self,
        scope: str,
        expires_in_hours: float = 1,
        token: str | None = None,
        user: User | None = None,
    ) -> OAuthAccessToken:
        token = token or f"pha_{generate_random_token()}"
        app = OAuthApplication.objects.create(
            name="PostHog Code",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=user or self.user,
        )
        return OAuthAccessToken.objects.create(
            user=user or self.user,
            application=app,
            token=token,
            expires=timezone.now() + timedelta(hours=expires_in_hours),
            scope=scope,
        )

    def _read_blob(self, cache_hash: str | None) -> dict | None:
        if cache_hash is None:
            return None
        raw = hypercache.cache_client.get(hypercache.get_cache_key(cache_hash))
        return None if raw is None or raw == "__missing__" else json.loads(raw)


class TestGatewayCredentialWireShape(GatewayCredentialTestMixin):
    # Mirrors the ai-gateway gateway-credential wire-shape decode test (internal/auth):
    # the literal key path and JSON shape are the cross-service contract.
    @parameterized.expand(["phs", "pha"])
    def test_blob_key_and_shape(self, kind: str):
        if kind == "phs":
            credential, token = self._make_secret_key([GATEWAY_SCOPE])
            expected_hash = hash_key_value(token)
            self.assertEqual(credential.secure_value, expected_hash)
        else:
            credential = self._make_oauth(GATEWAY_SCOPE)
            token = credential.token
            expected_hash = f"{SHA256_HASH_PREFIX}{credential.token_checksum}"
            self.assertEqual(hash_key_value(token), expected_hash)

        cache_hash = credential_hash(credential)
        assert cache_hash is not None
        self.assertEqual(cache_hash, expected_hash)
        self.assertTrue(cache_hash.startswith(SHA256_HASH_PREFIX))

        project_gateway_credential(credential)

        self.assertEqual(
            hypercache.get_cache_key(cache_hash),
            f"cache/team_tokens_hashed/{cache_hash}/team_metadata/gateway_credential.json",
        )

        blob = self._read_blob(cache_hash)
        assert blob is not None
        self.assertEqual(set(blob.keys()), set(GATEWAY_CREDENTIAL_FIELDS))
        self.assertEqual(blob["team_id"], self.team.id)
        self.assertGreater(blob["team_id"], 0)
        self.assertEqual(blob["project_token"], self.team.api_token)
        self.assertEqual(blob["scopes"], [GATEWAY_SCOPE])
        self.assertEqual(blob["billing_mode"], "internal")
        self.assertIsNone(blob["revoked_at"])

        # Raw token never appears in the key (only its hash).
        self.assertNotIn(token, hypercache.get_cache_key(cache_hash))

    def test_team_without_api_token_fails_closed(self):
        # team_id resolves but the team has no phc_ token to stamp — fail closed.
        key, _ = self._make_secret_key([GATEWAY_SCOPE])
        Team.objects.filter(pk=self.team.pk).update(api_token="")
        fresh = ProjectSecretAPIKey.objects.get(pk=key.pk)
        project_gateway_credential(fresh)
        self.assertIsNone(self._read_blob(credential_hash(fresh)))

    def test_oauth_ambiguous_org_root_fails_closed(self):
        # An OAuth app's org has two project-root teams, so the attribution team is
        # ambiguous — fail closed rather than guess.
        Team.objects.create(organization=self.organization, name="second root")
        credential = self._make_oauth(GATEWAY_SCOPE)
        project_gateway_credential(credential)
        self.assertIsNone(self._read_blob(credential_hash(credential)))

    def test_secret_key_in_child_env_attributes_to_parent(self):
        # An environment is a child of its project; a key minted there bills the
        # parent (canonical) project, carrying the parent's id and api_token.
        child = Team.objects.create(organization=self.organization, name="child env", parent_team=self.team)
        token = generate_random_token_secret()
        key = ProjectSecretAPIKey.objects.create(
            label="child key", team=child, secure_value=hash_key_value(token), scopes=[GATEWAY_SCOPE]
        )
        project_gateway_credential(key)
        blob = self._read_blob(credential_hash(key))
        assert blob is not None
        self.assertEqual(blob["team_id"], self.team.id)
        self.assertEqual(blob["project_token"], self.team.api_token)

    def test_overspend_allowance_omitted_when_unset(self):
        # Null = unset: the field is absent so the gateway falls back to its operator default.
        credential, _ = self._make_secret_key([GATEWAY_SCOPE])
        project_gateway_credential(credential)
        blob = self._read_blob(credential_hash(credential))
        assert blob is not None
        self.assertNotIn(OVERSPEND_ALLOWANCE_KEY, blob)

    @parameterized.expand(
        [
            ("whole", Decimal("5"), "5.000000"),
            ("explicit_zero", Decimal("0"), "0.000000"),
            ("fractional", Decimal("0.5"), "0.500000"),
            ("max", Decimal("10000"), "10000.000000"),
        ]
    )
    def test_overspend_allowance_projected_as_fixed_point_string(self, _name, value, expected):
        # update() bypasses signals (no Redis needed) and persists for the fresh team read.
        Team.objects.filter(pk=self.team.pk).update(llm_gateway_overspend_allowance_usd=value)
        credential, _ = self._make_secret_key([GATEWAY_SCOPE])
        project_gateway_credential(credential)
        blob = self._read_blob(credential_hash(credential))
        assert blob is not None
        # Pin the literal wire value, not a serializer round-trip.
        self.assertEqual(blob[OVERSPEND_ALLOWANCE_KEY], expected)
        self.assertIsInstance(blob[OVERSPEND_ALLOWANCE_KEY], str)


class TestOverspendAllowanceFormatting(BaseTest):
    @parameterized.expand(
        [
            ("whole", Decimal("5"), "5.000000"),
            ("zero", Decimal("0"), "0.000000"),
            ("max", Decimal("10000"), "10000.000000"),
            ("six_dp", Decimal("1.234567"), "1.234567"),
        ]
    )
    def test_format_is_fixed_point_never_scientific(self, _name, value, expected):
        formatted = format_overspend_allowance_usd(value)
        self.assertEqual(formatted, expected)
        self.assertNotIn("E", formatted.upper())

    @parameterized.expand(
        [
            ("whole", Decimal("5"), Decimal("5.000000")),
            ("zero", Decimal("0"), Decimal("0.000000")),
            ("max", Decimal("10000"), Decimal("10000.000000")),
            ("six_dp", Decimal("1.234567"), Decimal("1.234567")),
        ]
    )
    def test_validate_accepts_in_range(self, _name, value, expected):
        self.assertEqual(validate_overspend_allowance_usd(value), expected)

    @parameterized.expand(
        [
            ("negative", Decimal("-0.000001")),
            ("over_max", Decimal("10000.000001")),
            ("too_precise", Decimal("1.0000001")),
            ("nan", Decimal("NaN")),
        ]
    )
    def test_validate_rejects_out_of_contract(self, _name, value):
        with self.assertRaises(ValueError):
            validate_overspend_allowance_usd(value)


class TestOverspendAllowanceDBConstraint(BaseTest):
    # The CHECK constraint backstops update/bulk_update/shell/raw writes that bypass the validators.
    @parameterized.expand([("negative", Decimal("-1")), ("over_max", Decimal("10001"))])
    def test_db_rejects_out_of_range_update(self, _name, value):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Team.objects.filter(pk=self.team.pk).update(llm_gateway_overspend_allowance_usd=value)

    @parameterized.expand([("zero", Decimal("0")), ("max", Decimal("10000")), ("unset", None)])
    def test_db_accepts_in_range_update(self, _name, value):
        Team.objects.filter(pk=self.team.pk).update(llm_gateway_overspend_allowance_usd=value)
        self.team.refresh_from_db()
        self.assertEqual(self.team.llm_gateway_overspend_allowance_usd, value)


class TestGatewayCredentialScopeGating(GatewayCredentialTestMixin):
    @parameterized.expand(
        [
            ("secret_key_no_scope", ["feature_flag:read"], False),
            ("secret_key_wildcard_does_not_subsume", ["*"], False),
            ("secret_key_write_only_not_projected", ["llm_gateway:write"], False),
            ("secret_key_has_scope", [GATEWAY_SCOPE], True),
        ]
    )
    def test_secret_key_scope_gating(self, _name: str, scopes: list[str], should_write: bool):
        credential, _ = self._make_secret_key(scopes)
        project_gateway_credential(credential)
        self.assertEqual(self._read_blob(credential_hash(credential)) is not None, should_write)

    @parameterized.expand(
        [
            # "*" must NOT subsume the privileged gateway scope (RFC #1103); the
            # gateway rejects a "*" blob and the legacy wildcard is being retired.
            ("oauth_wildcard_does_not_subsume", "*", False),
            ("oauth_literal_scope", GATEWAY_SCOPE, True),
            ("oauth_no_scope", "feature_flag:read", False),
            ("oauth_write_only_not_projected", "llm_gateway:write", False),
            ("oauth_read_and_write_projected", "llm_gateway:read llm_gateway:write", True),
        ]
    )
    def test_oauth_scope_gating(self, _name: str, scope: str, should_write: bool):
        credential = self._make_oauth(scope)
        project_gateway_credential(credential)
        self.assertEqual(self._read_blob(credential_hash(credential)) is not None, should_write)


class TestGatewayCredentialFailClosed(GatewayCredentialTestMixin):
    def test_clear_removes_blob(self):
        credential, _ = self._make_secret_key([GATEWAY_SCOPE])
        project_gateway_credential(credential)
        cache_hash = credential_hash(credential)
        assert self._read_blob(cache_hash) is not None

        clear_gateway_credential(credential)
        self.assertIsNone(self._read_blob(cache_hash))

    def test_scope_removal_clears_blob(self):
        credential, _ = self._make_secret_key([GATEWAY_SCOPE])
        project_gateway_credential(credential)
        cache_hash = credential_hash(credential)
        assert self._read_blob(cache_hash) is not None

        credential.scopes = ["feature_flag:read"]
        project_gateway_credential(credential)
        self.assertIsNone(self._read_blob(cache_hash))

    def test_expired_oauth_token_clears(self):
        credential = self._make_oauth(GATEWAY_SCOPE, expires_in_hours=-1)
        project_gateway_credential(credential)
        self.assertIsNone(self._read_blob(credential_hash(credential)))

    # The user / scope-narrowing / membership / RBAC enforcement only applies to OAuth
    # — project secret keys carry no user, no scoped_*, and no membership. These cases
    # exercise the surviving OAuth authorization path.
    def test_inactive_user_clears(self):
        credential = self._make_oauth(GATEWAY_SCOPE)
        project_gateway_credential(credential)
        cache_hash = credential_hash(credential)
        assert self._read_blob(cache_hash) is not None

        self.user.is_active = False
        self.user.save()
        project_gateway_credential(credential)
        self.assertIsNone(self._read_blob(cache_hash))

    def test_oauth_scoped_team_outside_fails_closed(self):
        other = Team.objects.create(organization=self.organization, name="other")
        credential = self._make_oauth(GATEWAY_SCOPE)
        credential.scoped_teams = [other.id]
        project_gateway_credential(credential)
        self.assertIsNone(self._read_blob(credential_hash(credential)))

    def test_oauth_scoped_team_including_team_writes(self):
        credential = self._make_oauth(GATEWAY_SCOPE)
        credential.scoped_teams = [self.team.id]
        project_gateway_credential(credential)
        self.assertIsNotNone(self._read_blob(credential_hash(credential)))

    def test_oauth_scoped_to_child_environment_fails_closed(self):
        # The gateway is bound to the canonical (project root) team, and the Go
        # gateway authenticates at project level — it can't honor a per-environment
        # narrowing. A credential scoped only to a child environment of this project
        # deliberately fails closed rather than being silently widened to the whole
        # project. self.team is canonical (parent_team_id IS NULL); child is one of
        # its environments.
        child = Team.objects.create(organization=self.organization, name="child env", parent_team=self.team)
        credential = self._make_oauth(GATEWAY_SCOPE)
        credential.scoped_teams = [child.id]
        project_gateway_credential(credential)
        self.assertIsNone(self._read_blob(credential_hash(credential)))

    def test_oauth_scoped_org_outside_fails_closed(self):
        credential = self._make_oauth(GATEWAY_SCOPE)
        credential.scoped_organizations = ["00000000-0000-0000-0000-000000000000"]
        project_gateway_credential(credential)
        self.assertIsNone(self._read_blob(credential_hash(credential)))

    def test_oauth_scoped_org_matching_writes(self):
        credential = self._make_oauth(GATEWAY_SCOPE)
        credential.scoped_organizations = [str(self.organization.id)]
        project_gateway_credential(credential)
        self.assertIsNotNone(self._read_blob(credential_hash(credential)))

    def test_oauth_non_member_user_fails_closed(self):
        # A user removed from the billed team's org loses gateway access even
        # though the token, gateway, and is_active are untouched.
        credential = self._make_oauth(GATEWAY_SCOPE)
        project_gateway_credential(credential)
        cache_hash = credential_hash(credential)
        assert self._read_blob(cache_hash) is not None

        self.organization_membership.delete()
        project_gateway_credential(credential)
        self.assertIsNone(self._read_blob(cache_hash))

    @pytest.mark.ee
    def test_project_access_control_revoked_fails_closed(self):
        # A real access control revoking a member's access to the bound project
        # fails closed, even though org membership is intact. Uses a real
        # AccessControl (not a mock) so it also covers that a Team resolves to the
        # "project" resource and the access-control keying matches.
        from ee.models.rbac.access_control import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()

        member = User.objects.create_and_join(self.organization, "member@example.com", "password")
        membership = OrganizationMembership.objects.get(organization=self.organization, user=member)
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=membership,
            access_level="none",
        )
        credential = self._make_oauth(GATEWAY_SCOPE, user=member)
        project_gateway_credential(credential)
        self.assertIsNone(self._read_blob(credential_hash(credential)))


class TestGatewayCredentialTTL(GatewayCredentialTestMixin):
    def test_secret_key_written_with_capped_ttl(self):
        # Secret keys never expire, so the blob is capped at the short secret-key TTL the
        # hourly refresh keeps warm — not the 7-day default.
        key, _ = self._make_secret_key([GATEWAY_SCOPE])
        with patch.object(hypercache, "set_cache_value_redis_only") as mock_set:
            project_gateway_credential(key)
        self.assertEqual(mock_set.call_args.kwargs["ttl"], GATEWAY_CREDENTIAL_SECRET_KEY_CACHE_TTL)

    def test_oauth_blob_ttl_tracks_remaining_lifetime(self):
        # OAuth blobs live only as long as the token, so the gateway can't authenticate a
        # token past its expiry off a stale blob.
        credential = self._make_oauth(GATEWAY_SCOPE, expires_in_hours=2)
        with patch.object(hypercache, "set_cache_value_redis_only") as mock_set:
            project_gateway_credential(credential)
        ttl = mock_set.call_args.kwargs["ttl"]
        self.assertGreater(ttl, 2 * 60 * 60 - 60)
        self.assertLessEqual(ttl, 2 * 60 * 60)


class TestGatewayCredentialRefresh(GatewayCredentialTestMixin):
    def test_refresh_projects_eligible_credentials(self):
        # Many keys share the team's one gateway; secret_key, oauth, and ignored all resolve by team.
        secret_key, _ = self._make_secret_key([GATEWAY_SCOPE])
        oauth = self._make_oauth(GATEWAY_SCOPE)
        ignored, _ = self._make_secret_key(["feature_flag:read"])

        projected = refresh_all_gateway_credentials()

        self.assertGreaterEqual(projected, 2)
        self.assertIsNotNone(self._read_blob(credential_hash(secret_key)))
        self.assertIsNotNone(self._read_blob(credential_hash(oauth)))
        self.assertIsNone(self._read_blob(credential_hash(ignored)))


class TestGatewayCredentialTasks(GatewayCredentialTestMixin):
    def test_update_task_projects_secret_key(self):
        secret_key, _ = self._make_secret_key([GATEWAY_SCOPE])
        update_gateway_credential_cache_task(SECRET_KEY_KIND, str(secret_key.pk))
        self.assertIsNotNone(self._read_blob(credential_hash(secret_key)))

    def test_update_task_missing_credential_is_noop(self):
        update_gateway_credential_cache_task(SECRET_KEY_KIND, "does_not_exist")
        update_gateway_credential_cache_task("unknown_kind", "x")

    def test_reproject_user_task_projects_oauth(self):
        # reproject_user is user-scoped, so it covers OAuth only; secret keys have no user.
        oauth = self._make_oauth(GATEWAY_SCOPE)
        reproject_user_gateway_credentials_task(self.user.pk)
        self.assertIsNotNone(self._read_blob(credential_hash(oauth)))

    def test_reproject_team_task_projects_secret_keys_including_child_envs(self):
        # The team reproject catches secret keys on the team and its child environments;
        # a child-env key bills the canonical parent project.
        child = Team.objects.create(organization=self.organization, name="child env", parent_team=self.team)
        parent_key, _ = self._make_secret_key([GATEWAY_SCOPE])
        child_token = generate_random_token_secret()
        child_key = ProjectSecretAPIKey.objects.create(
            label="child key", team=child, secure_value=hash_key_value(child_token), scopes=[GATEWAY_SCOPE]
        )
        hypercache.cache_client.clear()

        reproject_team_gateway_credentials_task(self.team.pk)

        self.assertIsNotNone(self._read_blob(credential_hash(parent_key)))
        self.assertIsNotNone(self._read_blob(credential_hash(child_key)))

    def test_reproject_team_task_projects_org_oauth_tokens(self):
        # An OAuth token resolves by its application's org, so the team reproject catches
        # every gateway token in the team's organization.
        oauth = self._make_oauth(GATEWAY_SCOPE)
        hypercache.cache_client.clear()

        reproject_team_gateway_credentials_task(self.team.pk)

        self.assertIsNotNone(self._read_blob(credential_hash(oauth)))

    @patch("posthog.tasks.gateway_credential.settings")
    def test_refresh_task_noop_without_redis_url(self, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = None
        refresh_gateway_credentials()


class TestGatewayCredentialSignals(GatewayCredentialTestMixin):
    @patch("posthog.storage.gateway_credential_signal_handlers.transaction")
    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    @patch("posthog.tasks.gateway_credential.update_gateway_credential_cache_task.delay")
    def test_secret_key_save_enqueues_update(self, mock_delay, mock_settings, mock_transaction):
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        secret_key, _ = self._make_secret_key([GATEWAY_SCOPE])

        mock_delay.assert_called_with(SECRET_KEY_KIND, str(secret_key.pk))

    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    @patch("posthog.tasks.gateway_credential.update_gateway_credential_cache_task.delay")
    def test_secret_key_save_noop_without_redis_url(self, mock_delay, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = None
        self._make_secret_key([GATEWAY_SCOPE])
        mock_delay.assert_not_called()

    @patch("posthog.storage.gateway_credential_signal_handlers.transaction")
    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    @patch("posthog.tasks.gateway_credential.update_gateway_credential_cache_task.delay")
    def test_non_gateway_credential_save_does_not_enqueue(self, mock_delay, mock_settings, mock_transaction):
        # The hot path: ordinary credentials without the gateway scope must not
        # enqueue work, even when the gateway Redis is configured.
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        self._make_secret_key(["feature_flag:read"])

        mock_delay.assert_not_called()

    @patch("posthog.storage.gateway_credential_signal_handlers.transaction")
    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    @patch("posthog.tasks.gateway_credential.update_gateway_credential_cache_task.delay")
    def test_secret_key_rotation_clears_old_hash(self, mock_delay, mock_settings, mock_transaction):
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        old_token = generate_random_token_secret()
        secret_key, _ = self._make_secret_key([GATEWAY_SCOPE], token=old_token)
        old_hash = hash_key_value(old_token)
        project_gateway_credential(secret_key)
        assert self._read_blob(old_hash) is not None

        new_token = generate_random_token_secret()
        secret_key.secure_value = hash_key_value(new_token)
        secret_key.save()

        self.assertIsNone(self._read_blob(old_hash))

    @patch("posthog.storage.gateway_credential_signal_handlers.transaction")
    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    @patch("posthog.tasks.gateway_credential.update_gateway_credential_cache_task.delay")
    @patch("posthog.storage.gateway_credential_signal_handlers.clear_gateway_credential")
    def test_revoke_falls_back_to_async_when_sync_clear_fails(
        self, mock_clear, mock_delay, mock_settings, mock_transaction
    ):
        # Scope removed but the synchronous clear fails (e.g. transient Redis): queue the
        # task so the revoke self-heals instead of waiting out the blob TTL.
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        secret_key, _ = self._make_secret_key([GATEWAY_SCOPE])
        mock_clear.side_effect = Exception("redis down")
        secret_key.scopes = ["feature_flag:read"]
        secret_key.save()

        mock_delay.assert_called_with(SECRET_KEY_KIND, str(secret_key.pk))

    @patch("posthog.storage.gateway_credential_signal_handlers.transaction")
    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    @patch("posthog.tasks.gateway_credential.reproject_user_gateway_credentials_task.delay")
    def test_user_team_change_does_not_reproject(self, mock_delay, mock_settings, mock_transaction):
        # team_id comes from the bound gateway now, so a current-team switch
        # doesn't affect any blob — no reprojection.
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        other_team = Team.objects.create(organization=self.organization, name="Other team")
        user = User.objects.get(pk=self.user.pk)
        user.current_team = other_team
        user.save()

        mock_delay.assert_not_called()

    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    def test_secret_key_delete_clears_cache(self, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        secret_key, _ = self._make_secret_key([GATEWAY_SCOPE])
        project_gateway_credential(secret_key)
        cache_hash = credential_hash(secret_key)
        assert self._read_blob(cache_hash) is not None

        secret_key.delete()
        self.assertIsNone(self._read_blob(cache_hash))

    @patch("posthog.storage.gateway_credential_signal_handlers.transaction")
    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    @patch("posthog.tasks.gateway_credential.reproject_user_gateway_credentials_task")
    def test_reproject_retries_async_only_when_sync_fails(self, mock_task, mock_settings, mock_transaction):
        # A successful sync reprojection needs no retry; a sync failure (e.g. transient
        # Redis) must fall back to an async retry so a revoked blob can't outlive the TTL.
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        user = User.objects.get(pk=self.user.pk)
        user.is_active = False
        user.save()
        mock_task.assert_called_with(user.pk)  # synchronous attempt
        mock_task.delay.assert_not_called()  # succeeded — no retry queued

        mock_task.reset_mock()
        mock_task.side_effect = Exception("redis down")
        user.is_active = True
        user.save()
        mock_task.assert_called_with(user.pk)  # synchronous attempt
        mock_task.delay.assert_called_with(user.pk)  # failed — retry queued

    def test_user_deactivation_clears_blob_synchronously(self):
        # The on_commit invalidation reprojects synchronously, so a deactivated user's
        # blob is gone without waiting for the Celery task; .delay fires only if the sync
        # reprojection raises.
        oauth = self._make_oauth(GATEWAY_SCOPE)
        project_gateway_credential(oauth)
        cache_hash = credential_hash(oauth)
        assert self._read_blob(cache_hash) is not None

        with (
            patch("posthog.storage.gateway_credential_signal_handlers.settings") as mock_settings,
            patch("posthog.storage.gateway_credential_signal_handlers.transaction") as mock_transaction,
            patch("posthog.tasks.gateway_credential.reproject_user_gateway_credentials_task.delay") as mock_delay,
        ):
            mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
            mock_transaction.on_commit.side_effect = lambda fn: fn()
            user = User.objects.get(pk=self.user.pk)
            user.is_active = False
            user.save()

        self.assertIsNone(self._read_blob(cache_hash))
        mock_delay.assert_not_called()  # sync clear succeeded, no async retry needed

    @patch("posthog.storage.gateway_credential_signal_handlers.transaction")
    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    @patch("posthog.tasks.gateway_credential.reproject_user_gateway_credentials_task.delay")
    def test_membership_delete_reprojects(self, mock_delay, mock_settings, mock_transaction):
        # Losing org membership clears the user's OAuth blob synchronously; .delay is the
        # retry path and fires only if the sync reprojection raises.
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        oauth = self._make_oauth(GATEWAY_SCOPE)
        project_gateway_credential(oauth)
        cache_hash = credential_hash(oauth)
        assert self._read_blob(cache_hash) is not None

        self.organization_membership.delete()

        self.assertIsNone(self._read_blob(cache_hash))
        mock_delay.assert_not_called()

    @patch("posthog.storage.gateway_credential_signal_handlers.transaction")
    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    @patch("posthog.tasks.gateway_credential.reproject_user_gateway_credentials_task.delay")
    def test_membership_level_change_reprojects_user(self, mock_delay, mock_settings, mock_transaction):
        # A level change flips the OAuth RBAC admin-bypass without touching the credential.
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        membership = OrganizationMembership.objects.get(pk=self.organization_membership.pk)  # snapshot level
        membership.level = (
            OrganizationMembership.Level.ADMIN
            if membership.level != OrganizationMembership.Level.ADMIN
            else OrganizationMembership.Level.MEMBER
        )
        membership.save()

        mock_delay.assert_called_with(membership.user_id)

    def test_reproject_task_clears_inactive_user_blobs(self):
        oauth = self._make_oauth(GATEWAY_SCOPE)
        project_gateway_credential(oauth)
        cache_hash = credential_hash(oauth)
        assert self._read_blob(cache_hash) is not None

        self.user.is_active = False
        self.user.save()
        reproject_user_gateway_credentials_task(self.user.pk)
        self.assertIsNone(self._read_blob(cache_hash))

    @patch("posthog.storage.gateway_credential_signal_handlers.transaction")
    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    @patch("posthog.tasks.gateway_credential.update_gateway_credential_cache_task.delay")
    def test_deferred_load_rotation_clears_old_hash(self, mock_delay, mock_settings, mock_transaction):
        # Secret key loaded with secure_value/scopes deferred: the post_init snapshot
        # is skipped, so the pre_save fallback must re-read the old hash to clear it.
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        old_token = generate_random_token_secret()
        secret_key, _ = self._make_secret_key([GATEWAY_SCOPE], token=old_token)
        old_hash = hash_key_value(old_token)
        project_gateway_credential(secret_key)
        assert self._read_blob(old_hash) is not None

        deferred = ProjectSecretAPIKey.objects.only("id").get(pk=secret_key.pk)
        deferred.secure_value = hash_key_value(generate_random_token_secret())
        deferred.save()

        self.assertIsNone(self._read_blob(old_hash))

    @pytest.mark.ee
    @patch("posthog.storage.gateway_credential_signal_handlers.transaction")
    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    @patch("posthog.tasks.gateway_credential.reproject_team_gateway_credentials_task.delay")
    def test_project_access_control_change_reprojects_team(self, mock_delay, mock_settings, mock_transaction):
        from ee.models.rbac.access_control import AccessControl

        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
        )

        mock_delay.assert_called_with(self.team.id)

    @pytest.mark.ee
    @patch("posthog.storage.gateway_credential_signal_handlers.transaction")
    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    @patch("posthog.tasks.gateway_credential.reproject_user_gateway_credentials_task")
    def test_role_membership_change_reprojects_synchronously(self, mock_task, mock_settings, mock_transaction):
        # Role membership is per-user, so it reprojects synchronously, unlike the
        # team-wide access-control handler. The async retry fires only on sync failure.
        from ee.models.rbac.role import Role, RoleMembership

        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        role = Role.objects.create(name="engineers", organization=self.organization)
        RoleMembership.objects.create(user=self.user, role=role)

        mock_task.assert_called_with(self.user.pk)  # synchronous reprojection
        mock_task.delay.assert_not_called()  # sync succeeded — no retry queued

    @patch("posthog.storage.gateway_credential_signal_handlers.transaction")
    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    @patch("posthog.tasks.gateway_credential.reproject_team_gateway_credentials_task.delay")
    def test_team_api_token_rotation_reprojects(self, mock_delay, mock_settings, mock_transaction):
        # project_token in the blob is the team's api_token; rotation makes it stale.
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        team = Team.objects.get(pk=self.team.pk)  # snapshot api_token under patched setting
        team.api_token = "phc_rotated_for_test"
        team.save()

        mock_delay.assert_called_with(self.team.id)

    @parameterized.expand([("set", None, Decimal("5")), ("clear", Decimal("5"), None)])
    @patch("posthog.storage.gateway_credential_signal_handlers.transaction")
    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    @patch("posthog.tasks.gateway_credential.reproject_team_gateway_credentials_task.delay")
    def test_team_overspend_allowance_change_reprojects(
        self, _name, initial, new, mock_delay, mock_settings, mock_transaction
    ):
        # Both transitions between the two observable states (unset and set) reproject every
        # credential blob on the team, rather than waiting out the TTL.
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        if initial is not None:
            Team.objects.filter(pk=self.team.pk).update(llm_gateway_overspend_allowance_usd=initial)
        team = Team.objects.get(pk=self.team.pk)  # snapshot allowance at pre_save under patched setting
        team.llm_gateway_overspend_allowance_usd = new
        team.save()

        mock_delay.assert_called_with(self.team.id)

    @patch("posthog.storage.gateway_credential_signal_handlers.transaction")
    @patch("posthog.storage.gateway_credential_signal_handlers.settings")
    @patch("posthog.tasks.gateway_credential.reproject_team_gateway_credentials_task.delay")
    def test_team_save_without_gateway_field_change_does_not_reproject(
        self, mock_delay, mock_settings, mock_transaction
    ):
        # A save touching neither api_token nor llm_gateway_overspend_allowance_usd must not enqueue.
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        team = Team.objects.get(pk=self.team.pk)
        team.name = "renamed, no gateway field touched"
        team.save()

        mock_delay.assert_not_called()


@override_settings(AI_GATEWAY_REDIS_URL=_TEST_GATEWAY_REDIS_URL)
class TestGatewayCredentialLastUsedDrain(GatewayCredentialTestMixin):
    """The gateway can't write Django's DB, so it coalesces credential use into a
    Valkey hash; the drain stamps ProjectSecretAPIKey.last_used_at from it."""

    def setUp(self):
        super().setUp()
        # fakeredis is a per-URL singleton that survives the DB rollback; clear it.
        self.redis = get_client(_TEST_GATEWAY_REDIS_URL)
        self.redis.delete(GATEWAY_CREDENTIAL_LAST_USED_KEY)

    def _seed(self, marks: dict[str, int]) -> None:
        # Per-field, not mapping=, so str keys satisfy hset's str|bytes without Mapping's invariant key.
        for field, ts in marks.items():
            self.redis.hset(GATEWAY_CREDENTIAL_LAST_USED_KEY, field, ts)

    @staticmethod
    def _hash(secret_key: ProjectSecretAPIKey) -> str:
        assert secret_key.secure_value is not None  # set by _make_secret_key
        return secret_key.secure_value

    @staticmethod
    def _stored_ts(secret_key: ProjectSecretAPIKey) -> int:
        secret_key.refresh_from_db()
        assert secret_key.last_used_at is not None
        return int(secret_key.last_used_at.timestamp())

    def test_drain_stamps_secret_key_last_used(self):
        secret_key, _ = self._make_secret_key([GATEWAY_SCOPE])
        self.assertIsNone(secret_key.last_used_at)
        used_ts = int(timezone.now().timestamp())
        self._seed({self._hash(secret_key): used_ts})

        updated = drain_gateway_credential_last_used()

        self.assertEqual(updated, 1)
        self.assertEqual(self._stored_ts(secret_key), used_ts)
        # The hash is consumed so a stalled drain can't double-process it.
        self.assertFalse(self.redis.exists(GATEWAY_CREDENTIAL_LAST_USED_KEY))

    @parameterized.expand(
        [
            # name, last_used offset from now, gateway-mark offset from now, expect update
            ("respects_hour_throttle", timedelta(minutes=-10), timedelta(0), False),
            ("never_regresses", timedelta(0), timedelta(hours=-2), False),
            ("stamps_when_older_than_throttle", timedelta(hours=-3), timedelta(0), True),
        ]
    )
    def test_drain_throttle_and_regression(self, _name, initial_offset, gateway_offset, expect_update):
        now = timezone.now()
        secret_key, _ = self._make_secret_key([GATEWAY_SCOPE])
        initial = now + initial_offset
        ProjectSecretAPIKey.objects.filter(pk=secret_key.pk).update(last_used_at=initial)
        self._seed({self._hash(secret_key): int((now + gateway_offset).timestamp())})

        updated = drain_gateway_credential_last_used()

        if expect_update:
            self.assertEqual(updated, 1)
            self.assertEqual(self._stored_ts(secret_key), int((now + gateway_offset).timestamp()))
        else:
            self.assertEqual(updated, 0)
            self.assertEqual(self._stored_ts(secret_key), int(initial.timestamp()))

    def test_drain_ignores_unknown_hash(self):
        self._seed({f"{SHA256_HASH_PREFIX}deadbeef": int(timezone.now().timestamp())})

        self.assertEqual(drain_gateway_credential_last_used(), 0)

    def test_drain_empty_hash_is_noop(self):
        self.assertEqual(drain_gateway_credential_last_used(), 0)

    @override_settings(AI_GATEWAY_REDIS_URL=None)
    def test_drain_noop_without_redis_url(self):
        self.assertEqual(drain_gateway_credential_last_used(), 0)

    def test_task_runs_drain(self):
        secret_key, _ = self._make_secret_key([GATEWAY_SCOPE])
        used_ts = int(timezone.now().timestamp())
        self._seed({self._hash(secret_key): used_ts})

        drain_gateway_credential_last_used_task()

        self.assertEqual(self._stored_ts(secret_key), used_ts)
