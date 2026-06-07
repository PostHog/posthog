import json
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.api.oauth.test_dcr import generate_rsa_key
from posthog.constants import AvailableFeature
from posthog.models.gateway import Gateway
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import (
    SHA256_HASH_PREFIX,
    generate_random_token,
    generate_random_token_personal,
    hash_key_value,
)
from posthog.storage.first_party_gateway_policy_cache import (
    FIRST_PARTY_POLICY_FIELDS,
    clear_first_party_policy,
    credential_hash,
    first_party_gateway_policy_hypercache as hypercache,
    project_first_party_policy,
    refresh_all_first_party_policies,
)
from posthog.tasks.first_party_gateway_policy import (
    refresh_first_party_gateway_policies,
    reproject_user_first_party_policies_task,
    update_first_party_policy_cache_task,
)

GATEWAY_SCOPE = "llm_gateway:read"


@override_settings(OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": generate_rsa_key()})
class FirstPartyPolicyTestMixin(BaseTest):
    def setUp(self):
        super().setUp()
        # LocMemCache persists across tests in-process; isolate each test.
        hypercache.cache_client.clear()
        if self.user.current_team_id != self.team.id:
            self.user.current_team = self.team
            self.user.save()
        # The credential's bound gateway is the source of truth for team + slug.
        self.gateway = Gateway.all_teams.create(team=self.team, slug="posthog_code")

    def _make_pak(
        self, scopes: list[str], token: str | None = None, gateway: Gateway | None = None
    ) -> tuple[PersonalAPIKey, str]:
        token = token or generate_random_token_personal()
        key = PersonalAPIKey.objects.create(
            label="test key",
            user=self.user,
            secure_value=hash_key_value(token),
            scopes=scopes,
            gateway=gateway or self.gateway,
        )
        return key, token

    def _make_oauth(
        self,
        scope: str,
        expires_in_hours: float = 1,
        token: str | None = None,
        gateway: Gateway | None = None,
    ) -> OAuthAccessToken:
        token = token or f"pha_{generate_random_token()}"
        app = OAuthApplication.objects.create(
            name="PostHog Code",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
            gateway=gateway or self.gateway,
        )
        return OAuthAccessToken.objects.create(
            user=self.user,
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


class TestFirstPartyPolicyWireShape(FirstPartyPolicyTestMixin):
    # Mirrors ai-gateway internal/auth/firstparty_test.go::TestFirstPartyDjangoWireShapeDecodes:
    # the literal key path and JSON shape are the cross-service contract.
    @parameterized.expand(["phx", "pha"])
    def test_blob_key_and_shape(self, kind: str):
        if kind == "phx":
            credential, token = self._make_pak([GATEWAY_SCOPE])
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

        project_first_party_policy(credential)

        self.assertEqual(
            hypercache.get_cache_key(cache_hash),
            f"cache/team_tokens_hashed/{cache_hash}/team_metadata/first_party_policy.json",
        )

        blob = self._read_blob(cache_hash)
        assert blob is not None
        self.assertEqual(set(blob.keys()), set(FIRST_PARTY_POLICY_FIELDS))
        self.assertEqual(blob["team_id"], self.team.id)
        self.assertGreater(blob["team_id"], 0)
        self.assertEqual(blob["project_token"], self.team.api_token)
        self.assertEqual(blob["scopes"], [GATEWAY_SCOPE])
        self.assertEqual(blob["gateway_slug"], "posthog_code")
        self.assertEqual(blob["billing_mode"], "internal")
        self.assertIsNone(blob["revoked_at"])

        # Raw token never appears in the key (only its hash).
        self.assertNotIn(token, hypercache.get_cache_key(cache_hash))

    @parameterized.expand(["Posthog_Code", "slack app", "wizard/v2", "", "_leading"])
    def test_malformed_gateway_slug_fails_closed(self, slug: str):
        # Gateway.save() rejects these, so force one into the DB via update() to
        # exercise the projection's backstop: a slug the gateway can't route (or
        # that escapes its cache-key path) must not be projected.
        pak, _ = self._make_pak([GATEWAY_SCOPE])
        Gateway.all_teams.filter(pk=self.gateway.pk).update(slug=slug)
        fresh = PersonalAPIKey.objects.get(pk=pak.pk)  # reload so gateway.slug isn't cached
        project_first_party_policy(fresh)
        self.assertIsNone(self._read_blob(credential_hash(fresh)))

    def test_unbound_credential_fails_closed(self):
        # A scoped credential with no gateway binding can't resolve a team — fail closed.
        pak, _ = self._make_pak([GATEWAY_SCOPE])
        PersonalAPIKey.objects.filter(pk=pak.pk).update(gateway=None)
        fresh = PersonalAPIKey.objects.get(pk=pak.pk)
        project_first_party_policy(fresh)
        self.assertIsNone(self._read_blob(credential_hash(fresh)))


class TestFirstPartyPolicyScopeGating(FirstPartyPolicyTestMixin):
    @parameterized.expand(
        [
            ("pak_no_scope", ["feature_flag:read"], False),
            ("pak_wildcard_does_not_subsume", ["*"], False),
            ("pak_has_scope", [GATEWAY_SCOPE], True),
        ]
    )
    def test_pak_scope_gating(self, _name: str, scopes: list[str], should_write: bool):
        credential, _ = self._make_pak(scopes)
        project_first_party_policy(credential)
        self.assertEqual(self._read_blob(credential_hash(credential)) is not None, should_write)

    @parameterized.expand(
        [
            # "*" must NOT subsume the privileged gateway scope (RFC #1103); the
            # gateway rejects a "*" blob and the legacy wildcard is being retired.
            ("oauth_wildcard_does_not_subsume", "*", False),
            ("oauth_literal_scope", GATEWAY_SCOPE, True),
            ("oauth_no_scope", "feature_flag:read", False),
        ]
    )
    def test_oauth_scope_gating(self, _name: str, scope: str, should_write: bool):
        credential = self._make_oauth(scope)
        project_first_party_policy(credential)
        self.assertEqual(self._read_blob(credential_hash(credential)) is not None, should_write)


class TestFirstPartyPolicyFailClosed(FirstPartyPolicyTestMixin):
    def test_clear_removes_blob(self):
        credential, _ = self._make_pak([GATEWAY_SCOPE])
        project_first_party_policy(credential)
        cache_hash = credential_hash(credential)
        assert self._read_blob(cache_hash) is not None

        clear_first_party_policy(credential)
        self.assertIsNone(self._read_blob(cache_hash))

    def test_scope_removal_clears_blob(self):
        credential, token = self._make_pak([GATEWAY_SCOPE])
        project_first_party_policy(credential)
        cache_hash = credential_hash(credential)
        assert self._read_blob(cache_hash) is not None

        credential.scopes = ["feature_flag:read"]
        project_first_party_policy(credential)
        self.assertIsNone(self._read_blob(cache_hash))

    def test_expired_oauth_token_clears(self):
        credential = self._make_oauth(GATEWAY_SCOPE, expires_in_hours=-1)
        project_first_party_policy(credential)
        self.assertIsNone(self._read_blob(credential_hash(credential)))

    def test_inactive_user_clears(self):
        credential, _ = self._make_pak([GATEWAY_SCOPE])
        project_first_party_policy(credential)
        cache_hash = credential_hash(credential)
        assert self._read_blob(cache_hash) is not None

        self.user.is_active = False
        self.user.save()
        project_first_party_policy(credential)
        self.assertIsNone(self._read_blob(cache_hash))

    def test_scoped_team_outside_current_team_fails_closed(self):
        other = Team.objects.create(organization=self.organization, name="other")
        credential, _ = self._make_pak([GATEWAY_SCOPE])
        credential.scoped_teams = [other.id]
        project_first_party_policy(credential)
        self.assertIsNone(self._read_blob(credential_hash(credential)))

    def test_scoped_team_including_current_team_writes(self):
        credential, _ = self._make_pak([GATEWAY_SCOPE])
        credential.scoped_teams = [self.team.id]
        project_first_party_policy(credential)
        self.assertIsNotNone(self._read_blob(credential_hash(credential)))

    def test_credential_scoped_to_child_environment_fails_closed(self):
        # The gateway is bound to the canonical (project root) team, and the Go
        # gateway authenticates at project level — it can't honor a per-environment
        # narrowing. A credential scoped only to a child environment of this project
        # deliberately fails closed rather than being silently widened to the whole
        # project. self.team is canonical (parent_team_id IS NULL); child is one of
        # its environments.
        child = Team.objects.create(organization=self.organization, name="child env", parent_team=self.team)
        credential, _ = self._make_pak([GATEWAY_SCOPE])
        credential.scoped_teams = [child.id]
        project_first_party_policy(credential)
        self.assertIsNone(self._read_blob(credential_hash(credential)))

    def test_scoped_org_outside_current_team_org_fails_closed(self):
        credential, _ = self._make_pak([GATEWAY_SCOPE])
        credential.scoped_organizations = ["00000000-0000-0000-0000-000000000000"]
        project_first_party_policy(credential)
        self.assertIsNone(self._read_blob(credential_hash(credential)))

    def test_scoped_org_matching_current_team_org_writes(self):
        credential, _ = self._make_pak([GATEWAY_SCOPE])
        credential.scoped_organizations = [str(self.organization.id)]
        project_first_party_policy(credential)
        self.assertIsNotNone(self._read_blob(credential_hash(credential)))

    def test_non_member_user_fails_closed(self):
        # A user removed from the billed team's org loses gateway access even
        # though the key, gateway, and is_active are untouched.
        credential, _ = self._make_pak([GATEWAY_SCOPE])
        project_first_party_policy(credential)
        cache_hash = credential_hash(credential)
        assert self._read_blob(cache_hash) is not None

        self.organization_membership.delete()
        project_first_party_policy(credential)
        self.assertIsNone(self._read_blob(cache_hash))

    @patch("posthog.models.organization.Organization.is_feature_available", return_value=True)
    def test_org_disallowing_member_personal_keys_fails_closed(self, _mock_feature):
        # Org security setting can forbid non-admin members from using personal keys.
        self.organization.members_can_use_personal_api_keys = False
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        credential, _ = self._make_pak([GATEWAY_SCOPE])
        project_first_party_policy(credential)
        self.assertIsNone(self._read_blob(credential_hash(credential)))

    @patch("posthog.models.organization.Organization.is_feature_available", return_value=True)
    def test_org_disallowing_member_personal_keys_still_writes_for_admin(self, _mock_feature):
        self.organization.members_can_use_personal_api_keys = False
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        credential, _ = self._make_pak([GATEWAY_SCOPE])
        project_first_party_policy(credential)
        self.assertIsNotNone(self._read_blob(credential_hash(credential)))

    @patch("posthog.models.organization.Organization.is_feature_available", return_value=True)
    def test_org_disallowing_member_personal_keys_does_not_affect_oauth(self, _mock_feature):
        # The personal-key restriction is PAK-only; OAuth tokens are exempt.
        self.organization.members_can_use_personal_api_keys = False
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        credential = self._make_oauth(GATEWAY_SCOPE)
        project_first_party_policy(credential)
        self.assertIsNotNone(self._read_blob(credential_hash(credential)))

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
        credential = PersonalAPIKey.objects.create(
            label="member key",
            user=member,
            secure_value=hash_key_value(generate_random_token_personal()),
            scopes=[GATEWAY_SCOPE],
            gateway=self.gateway,
        )
        project_first_party_policy(credential)
        self.assertIsNone(self._read_blob(credential_hash(credential)))


class TestFirstPartyPolicyRefresh(FirstPartyPolicyTestMixin):
    def test_refresh_projects_eligible_credentials(self):
        # Many keys can share one gateway; pak, oauth, and ignored all bind to self.gateway.
        pak, _ = self._make_pak([GATEWAY_SCOPE])
        oauth = self._make_oauth(GATEWAY_SCOPE)
        ignored, _ = self._make_pak(["feature_flag:read"])

        projected = refresh_all_first_party_policies()

        self.assertGreaterEqual(projected, 2)
        self.assertIsNotNone(self._read_blob(credential_hash(pak)))
        self.assertIsNotNone(self._read_blob(credential_hash(oauth)))
        self.assertIsNone(self._read_blob(credential_hash(ignored)))


class TestFirstPartyPolicyTasks(FirstPartyPolicyTestMixin):
    def test_update_task_projects_pak(self):
        pak, _ = self._make_pak([GATEWAY_SCOPE])
        update_first_party_policy_cache_task("personal_api_key", str(pak.pk))
        self.assertIsNotNone(self._read_blob(credential_hash(pak)))

    def test_update_task_missing_credential_is_noop(self):
        update_first_party_policy_cache_task("personal_api_key", "does_not_exist")
        update_first_party_policy_cache_task("unknown_kind", "x")

    def test_reproject_user_task(self):
        pak, _ = self._make_pak([GATEWAY_SCOPE])
        reproject_user_first_party_policies_task(self.user.pk)
        self.assertIsNotNone(self._read_blob(credential_hash(pak)))

    @patch("posthog.tasks.first_party_gateway_policy.settings")
    def test_refresh_task_noop_without_redis_url(self, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = None
        refresh_first_party_gateway_policies()


class TestFirstPartyPolicySignals(FirstPartyPolicyTestMixin):
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.update_first_party_policy_cache_task.delay")
    def test_pak_save_enqueues_update(self, mock_delay, mock_settings, mock_transaction):
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        pak, _ = self._make_pak([GATEWAY_SCOPE])

        mock_delay.assert_called_with("personal_api_key", str(pak.pk))

    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.update_first_party_policy_cache_task.delay")
    def test_pak_save_noop_without_redis_url(self, mock_delay, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = None
        self._make_pak([GATEWAY_SCOPE])
        mock_delay.assert_not_called()

    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.update_first_party_policy_cache_task.delay")
    def test_non_gateway_credential_save_does_not_enqueue(self, mock_delay, mock_settings, mock_transaction):
        # The hot path: ordinary credentials without the gateway scope must not
        # enqueue work, even when the gateway Redis is configured.
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        self._make_pak(["feature_flag:read"])

        mock_delay.assert_not_called()

    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.update_first_party_policy_cache_task.delay")
    def test_pak_rotation_clears_old_hash(self, mock_delay, mock_settings, mock_transaction):
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        old_token = generate_random_token_personal()
        pak, _ = self._make_pak([GATEWAY_SCOPE], token=old_token)
        old_hash = hash_key_value(old_token)
        project_first_party_policy(pak)
        assert self._read_blob(old_hash) is not None

        new_token = generate_random_token_personal()
        pak.secure_value = hash_key_value(new_token)
        pak.save()

        self.assertIsNone(self._read_blob(old_hash))

    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.reproject_user_first_party_policies_task.delay")
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

    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.settings")
    def test_pak_delete_clears_cache(self, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        pak, _ = self._make_pak([GATEWAY_SCOPE])
        project_first_party_policy(pak)
        cache_hash = credential_hash(pak)
        assert self._read_blob(cache_hash) is not None

        pak.delete()
        self.assertIsNone(self._read_blob(cache_hash))

    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.reproject_user_first_party_policies_task.delay")
    def test_user_deactivation_reprojects(self, mock_delay, mock_settings, mock_transaction):
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        user = User.objects.get(pk=self.user.pk)
        user.is_active = False
        user.save()

        mock_delay.assert_called_with(user.pk)

    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.reproject_user_first_party_policies_task.delay")
    def test_membership_delete_reprojects(self, mock_delay, mock_settings, mock_transaction):
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        self.organization_membership.delete()

        mock_delay.assert_called_with(self.user.pk)

    def test_reproject_task_clears_inactive_user_blobs(self):
        pak, _ = self._make_pak([GATEWAY_SCOPE])
        project_first_party_policy(pak)
        cache_hash = credential_hash(pak)
        assert self._read_blob(cache_hash) is not None

        self.user.is_active = False
        self.user.save()
        reproject_user_first_party_policies_task(self.user.pk)
        self.assertIsNone(self._read_blob(cache_hash))

    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.update_first_party_policy_cache_task.delay")
    def test_deferred_load_rotation_clears_old_hash(self, mock_delay, mock_settings, mock_transaction):
        # PAK loaded with secure_value/scopes deferred: the post_init snapshot is
        # skipped, so the pre_save fallback must re-read the old hash to clear it.
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        old_token = generate_random_token_personal()
        pak, _ = self._make_pak([GATEWAY_SCOPE], token=old_token)
        old_hash = hash_key_value(old_token)
        project_first_party_policy(pak)
        assert self._read_blob(old_hash) is not None

        deferred = PersonalAPIKey.objects.only("id", "user").get(pk=pak.pk)
        deferred.secure_value = hash_key_value(generate_random_token_personal())
        deferred.save()

        self.assertIsNone(self._read_blob(old_hash))

    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.settings")
    @patch(
        "posthog.storage.first_party_gateway_policy_signal_handlers.reproject_gateway_first_party_policies_task.delay"
    )
    def test_gateway_slug_change_reprojects(self, mock_delay, mock_settings, mock_transaction):
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        gateway = Gateway.all_teams.create(team=self.team, slug="wizard")
        reloaded = Gateway.all_teams.get(pk=gateway.pk)  # snapshot old slug under patched setting
        reloaded.slug = "wizard_v2"
        reloaded.save()

        mock_delay.assert_called_with(str(gateway.pk))

    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.settings")
    def test_gateway_delete_clears_bound_credential_blobs(self, mock_settings, mock_transaction):
        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        pak, _ = self._make_pak([GATEWAY_SCOPE])
        project_first_party_policy(pak)
        cache_hash = credential_hash(pak)
        assert self._read_blob(cache_hash) is not None

        self.gateway.delete()
        self.assertIsNone(self._read_blob(cache_hash))

    @pytest.mark.ee
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.reproject_team_first_party_policies_task.delay")
    def test_project_access_control_change_reprojects_team(self, mock_delay, mock_settings, mock_transaction):
        from ee.models.rbac.access_control import AccessControl

        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
        )

        mock_delay.assert_called_with(self.team.id)

    @pytest.mark.ee
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.transaction")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.settings")
    @patch("posthog.storage.first_party_gateway_policy_signal_handlers.reproject_user_first_party_policies_task.delay")
    def test_role_membership_change_reprojects_user(self, mock_delay, mock_settings, mock_transaction):
        from ee.models.rbac.role import Role, RoleMembership

        mock_settings.AI_GATEWAY_REDIS_URL = "redis://localhost"
        mock_transaction.on_commit.side_effect = lambda fn: fn()

        role = Role.objects.create(name="engineers", organization=self.organization)
        RoleMembership.objects.create(user=self.user, role=role)

        mock_delay.assert_called_with(self.user.pk)
