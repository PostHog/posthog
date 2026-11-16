from datetime import datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.signing import TimestampSigner
from django.test import override_settings
from django.utils import timezone

from loginas import settings as loginas_settings
from parameterized import parameterized
from rest_framework import status

from posthog.api.organization_personal_api_key_actions import OrganizationPersonalAPIKeyActions
from posthog.constants import AvailableFeature
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.utils import generate_random_token_personal, hash_key_value, mask_key_value
from posthog.storage.team_access_cache import TOKEN_CACHE_PREFIX, token_auth_cache
from posthog.tasks.email import send_personal_api_keys_changed_by_org_admin


class TestOrganizationPersonalAPIKeyAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS, "name": "organization_security_settings"}
        ]
        self.organization.save()

    def _create_key(self, user, *, value=None, **kwargs):
        value = value or generate_random_token_personal()
        return PersonalAPIKey.objects.create(
            user=user,
            label=kwargs.pop("label", "key"),
            secure_value=hash_key_value(value),
            mask_value=mask_key_value(value),
            scopes=kwargs.pop("scopes", ["insight:read"]),
            **kwargs,
        )

    def _url(self, org=None):
        return f"/api/organizations/{(org or self.organization).id}/personal_api_keys/"

    def _set_level(self, level):
        self.organization_membership.level = level
        self.organization_membership.save()

    def _action_url(self, key: PersonalAPIKey, action: str) -> str:
        return f"{self._url()}{key.id}/{action}/"

    def _create_owner_in_other_orgs(self, *, owner_joins_b: bool = True) -> User:
        self.org_b = Organization.objects.create(name="action-probe-org-b-2c9e4a")
        team_b = Team.objects.create(organization=self.org_b, name="b-team")
        org_c = Organization.objects.create(name="action-probe-org-c-2c9e4a")
        team_c = Team.objects.create(organization=org_c, name="c-team")
        owner = User.objects.create_and_join(self.organization, "key-owner@example.com", None)
        if owner_joins_b:
            OrganizationMembership.objects.create(user=owner, organization=self.org_b)
        OrganizationMembership.objects.create(user=owner, organization=org_c).delete()
        self.team_refs = {"O": self.team.id, "B": team_b.id, "C": team_c.id, "deleted": team_c.id + 1000}
        self.org_refs = {"O": str(self.organization.id), "B": str(self.org_b.id), "C": str(org_c.id)}
        return owner

    def _create_scoped_key(self, owner: User, team_refs: tuple[str, ...], org_refs: tuple[str, ...], **kwargs):
        return self._create_key(
            owner,
            scoped_teams=[self.team_refs[ref] for ref in team_refs] or None,
            scoped_organizations=[self.org_refs[ref] for ref in org_refs] or None,
            **kwargs,
        )

    def test_admin_can_list_member_keys(self):
        self._set_level(OrganizationMembership.Level.ADMIN)
        member = User.objects.create_and_join(self.organization, "m@x.com", None)
        self._create_key(member, label="member-key")

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1

    def test_owner_can_list(self):
        self._set_level(OrganizationMembership.Level.OWNER)
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK

    def test_plain_member_is_forbidden(self):
        self._set_level(OrganizationMembership.Level.MEMBER)
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_response_never_exposes_secret_or_label(self):
        self._set_level(OrganizationMembership.Level.ADMIN)
        self._create_key(self.user, label="super-secret-label")

        response = self.client.get(self._url())

        body = response.json()
        assert response.status_code == status.HTTP_200_OK
        row = body["results"][0]
        assert "label" not in row
        assert "secure_value" not in row
        assert "value" not in row
        assert set(row.keys()) == {
            "id",
            "owner",
            "mask_value",
            "scopes",
            "access_scope",
            "reaches_other_organizations",
            "last_used_at",
            "created_at",
        }
        assert row["owner"]["email"] == self.user.email

    def test_access_scope_values(self):
        self._set_level(OrganizationMembership.Level.ADMIN)
        self._create_key(self.user, label="unscoped")
        self._create_key(self.user, label="org", scoped_organizations=[str(self.organization.id)])
        self._create_key(self.user, label="team", scoped_teams=[self.team.id])

        results = self.client.get(self._url()).json()["results"]
        scope_types = {r["access_scope"]["type"] for r in results}

        assert scope_types == {"all", "organization", "projects"}
        projects_row = next(r for r in results if r["access_scope"]["type"] == "projects")
        assert projects_row["access_scope"]["projects"] == [{"id": self.team.id, "name": self.team.name}]

    @parameterized.expand(
        [
            ("unscoped_single_org", False, (), (), False),
            ("unscoped_multi_org", True, (), (), True),
            ("org_scoped_o_and_b", True, (), ("O", "B"), True),
            ("org_scoped_o_and_left_c", True, (), ("O", "C"), False),
            ("team_scoped_o_and_b", True, ("O", "B"), (), True),
            ("team_scoped_o_and_left_c", True, ("O", "C"), (), False),
            ("teams_o_b_orgs_o_only", True, ("O", "B"), ("O",), False),
        ]
    )
    def test_reaches_other_organizations(
        self, _name: str, owner_joins_b: bool, team_refs: tuple[str, ...], org_refs: tuple[str, ...], expected: bool
    ) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        org_b = Organization.objects.create(name="reach-probe-org-b-7f3c1d")
        team_b = Team.objects.create(organization=org_b, name="b-team")
        org_c = Organization.objects.create(name="reach-probe-org-c-7f3c1d")
        team_c = Team.objects.create(organization=org_c, name="c-team")
        owner = User.objects.create_and_join(self.organization, "owner@x.com", None)
        OrganizationMembership.objects.create(user=self.user, organization=org_b)
        if owner_joins_b:
            OrganizationMembership.objects.create(user=owner, organization=org_b)
        OrganizationMembership.objects.create(user=owner, organization=org_c).delete()
        teams = {"O": self.team.id, "B": team_b.id, "C": team_c.id}
        orgs = {"O": str(self.organization.id), "B": str(org_b.id), "C": str(org_c.id)}
        self._create_key(
            owner,
            scoped_teams=[teams[ref] for ref in team_refs] or None,
            scoped_organizations=[orgs[ref] for ref in org_refs] or None,
        )

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["reaches_other_organizations"] is expected
        assert str(org_b.id).encode() not in response.content
        assert org_b.name.encode() not in response.content

    def test_excludes_other_org_keys(self):
        self._set_level(OrganizationMembership.Level.ADMIN)
        other_org = Organization.objects.create(name="other")
        Team.objects.create(organization=other_org, name="t")
        outsider = User.objects.create_and_join(other_org, "out@x.com", None)
        self._create_key(outsider, label="outsider")

        assert self.client.get(self._url()).json()["count"] == 0

    def test_requires_organization_security_settings_feature(self):
        self._set_level(OrganizationMembership.Level.ADMIN)
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert response.json()["code"] == "payment_required"

    @parameterized.expand(
        [
            ("unscoped_multi_org", True, (), ()),
            ("org_scoped_multi_org", True, (), ("O", "B")),
            ("team_scoped_multi_org", True, ("O", "B"), ()),
            ("team_and_org_scoped_multi_org", True, ("O", "B"), ("O", "B")),
            ("unscoped_owner_only_in_o", False, (), ()),
            ("org_scoped_to_o", True, (), ("O",)),
            ("org_scoped_to_o_and_left_c", True, (), ("O", "C")),
            ("teams_o_b_orgs_o", True, ("O", "B"), ("O",)),
            ("teams_o_orgs_o_b", True, ("O",), ("O", "B")),
            ("teams_o_and_deleted_team", False, ("O", "deleted"), ()),
        ]
    )
    def test_revoke_deletes_key_regardless_of_other_org_access(
        self, _name: str, owner_joins_b: bool, team_refs: tuple[str, ...], org_refs: tuple[str, ...]
    ) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        owner = self._create_owner_in_other_orgs(owner_joins_b=owner_joins_b)
        old_value = generate_random_token_personal()
        key = self._create_scoped_key(owner, team_refs, org_refs, value=old_value, scopes=["user:read"])
        self.client.logout()
        assert self.client.get("/api/users/@me/", HTTP_AUTHORIZATION=f"Bearer {old_value}").status_code == 200
        self.client.force_login(self.user)

        response = self.client.post(self._action_url(key, "revoke"))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"outcome": "deleted"}
        assert not PersonalAPIKey.objects.filter(pk=key.pk).exists()
        self.client.logout()
        assert (
            self.client.get("/api/users/@me/", HTTP_AUTHORIZATION=f"Bearer {old_value}").status_code
            == status.HTTP_401_UNAUTHORIZED
        )

    @parameterized.expand([("single_org", ("O",)), ("multi_org", ("O", "B"))])
    def test_roll_replaces_secret_without_revealing_it(self, _name: str, org_refs: tuple[str, ...]) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        owner = self._create_owner_in_other_orgs()
        old_value = generate_random_token_personal()
        key = self._create_scoped_key(
            owner,
            (),
            org_refs,
            value=old_value,
            label="deploy-key",
            scopes=["user:read"],
            expires_at=timezone.now() + timedelta(days=30),
        )
        before = PersonalAPIKey.objects.get(pk=key.pk)
        self.client.logout()
        assert self.client.get("/api/users/@me/", HTTP_AUTHORIZATION=f"Bearer {old_value}").status_code == 200
        self.client.force_login(self.user)

        response = self.client.post(self._action_url(key, "roll"))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"outcome": "rolled"}
        key.refresh_from_db()
        assert (key.label, key.scopes, key.scoped_teams, key.scoped_organizations, key.expires_at) == (
            before.label,
            before.scopes,
            before.scoped_teams,
            before.scoped_organizations,
            before.expires_at,
        )
        assert key.mask_value != before.mask_value
        assert key.secure_value != before.secure_value
        self.client.logout()
        response = self.client.get("/api/users/@me/", HTTP_AUTHORIZATION=f"Bearer {old_value}")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @parameterized.expand([("roll",), ("revoke",)])
    @override_settings(FLAGS_REDIS_URL=settings.REDIS_URL)
    def test_actions_invalidate_auth_cache(self, action: str) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        owner = self._create_owner_in_other_orgs()
        key = self._create_scoped_key(owner, (), ("O", "B"))

        cache_key = f"{TOKEN_CACHE_PREFIX}{key.secure_value}"
        token_auth_cache.redis.set(cache_key, "cached-auth", ex=60)
        self.addCleanup(token_auth_cache.redis.delete, cache_key)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._action_url(key, action))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert token_auth_cache.redis.get(cache_key) is None

    @parameterized.expand(
        [
            ("roll", "roll", ("O", "B"), ["updated"], "updated"),
            ("revoke_delete", "revoke", ("O",), ["deleted"], None),
            ("revoke_shared", "revoke", ("O", "B"), ["deleted"], "deleted"),
        ]
    )
    def test_actions_write_activity_in_org_with_admin_actor(
        self,
        _name: str,
        action: str,
        org_refs: tuple[str, ...],
        expected_activities_in_o: list[str],
        expected_activity_in_b: str | None,
    ) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        owner = self._create_owner_in_other_orgs()
        key = self._create_scoped_key(owner, (), org_refs)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._action_url(key, action))

        assert response.status_code == status.HTTP_200_OK, response.content
        rows = list(ActivityLog.objects.filter(scope="PersonalAPIKey", item_id=str(key.id)).exclude(activity="created"))
        rows_in_o = [row for row in rows if row.organization_id == self.organization.id]
        assert sorted(((row.activity, row.user) for row in rows_in_o), key=lambda pair: pair[0]) == [
            (activity, self.user) for activity in expected_activities_in_o
        ]
        rows_in_b = [row for row in rows if row.organization_id == self.org_b.id]
        if expected_activity_in_b is not None:
            assert len(rows_in_b) == 1
            row_in_b = rows_in_b[0]
            assert row_in_b.detail is not None
            assert (row_in_b.activity, row_in_b.user, row_in_b.is_system) == (expected_activity_in_b, None, False)
            assert row_in_b.detail["context"]["acted_by_user_outside_organization"] is True
        else:
            assert rows_in_b == []

    @parameterized.expand([("roll",), ("revoke",)])
    def test_key_outside_org_is_not_found(self, action: str) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        owner = self._create_owner_in_other_orgs()
        other_org = Organization.objects.create(name="outsider-org-2c9e4a")
        outsider = User.objects.create_and_join(other_org, "outsider@example.com", None)
        keys_not_reaching_o = [
            self._create_key(outsider, label="outsider"),
            self._create_scoped_key(owner, (), ("B",), label="org-b"),
            self._create_scoped_key(owner, ("O", "B"), ("B",), label="teams-o-b-org-b"),
        ]
        key_in_o = self._create_scoped_key(owner, (), ("O",))
        secure_values = {key.pk: key.secure_value for key in [*keys_not_reaching_o, key_in_o]}

        for key in keys_not_reaching_o:
            response = self.client.post(self._action_url(key, action))
            assert response.status_code == status.HTTP_404_NOT_FOUND, key.label
        self._set_level(OrganizationMembership.Level.MEMBER)
        assert self.client.post(self._action_url(key_in_o, action)).status_code == status.HTTP_403_FORBIDDEN
        assert dict(PersonalAPIKey.objects.filter(pk__in=secure_values).values_list("pk", "secure_value")) == (
            secure_values
        )

    @parameterized.expand([("roll",), ("revoke",)])
    def test_admin_can_invalidate_organization_owner_key(self, action: str) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        owner = User.objects.create_and_join(
            self.organization, "org-owner@example.com", None, level=OrganizationMembership.Level.OWNER
        )
        key = self._create_key(owner)
        old_secret = key.secure_value

        response = self.client.post(self._action_url(key, action))

        assert response.status_code == status.HTTP_200_OK, response.content
        if action == "roll":
            assert PersonalAPIKey.objects.get(pk=key.pk).secure_value != old_secret
        else:
            assert not PersonalAPIKey.objects.filter(pk=key.pk).exists()

    @parameterized.expand([(action, change) for action in ("roll", "revoke") for change in ("scope", "membership")])
    @patch.object(send_personal_api_keys_changed_by_org_admin, "delay")
    def test_access_lost_before_lock_prevents_action(self, action: str, change: str, mock_delay: MagicMock) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        owner = self._create_owner_in_other_orgs()
        key = self._create_scoped_key(owner, (), ("O", "B"))
        lock = OrganizationPersonalAPIKeyActions._lock

        def lose_access_then_lock(key_id: str, owner_id: int) -> PersonalAPIKey | None:
            if change == "scope":
                PersonalAPIKey.objects.filter(pk=key_id).update(scoped_organizations=[str(self.org_b.id)])
            else:
                OrganizationMembership.objects.filter(user_id=owner_id, organization=self.organization).delete()
            return lock(key_id, owner_id)

        with (
            patch.object(OrganizationPersonalAPIKeyActions, "_lock", side_effect=lose_access_then_lock),
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.post(self._action_url(key, action))

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
        assert PersonalAPIKey.objects.get(pk=key.pk).secure_value == key.secure_value
        assert (
            not ActivityLog.objects.filter(scope="PersonalAPIKey", item_id=str(key.id))
            .exclude(activity="created")
            .exists()
        )
        mock_delay.assert_not_called()

    @parameterized.expand([("roll",), ("revoke",)])
    def test_actions_require_recent_authentication(self, action: str) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        key = self._create_key(User.objects.create_and_join(self.organization, "member@example.com", None))
        url = self._action_url(key, action)

        with time_machine.travel(
            datetime.now() + timedelta(seconds=settings.SESSION_SENSITIVE_ACTIONS_AGE + 10), tick=False
        ):
            response = self.client.post(url)
            list_response = self.client.get(self._url())

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.json()["code"] == "sensitive_action_required_reauth"
        assert list_response.status_code == status.HTTP_200_OK, list_response.content

    @parameterized.expand(
        [(action, auth) for action in ("roll", "revoke") for auth in ("personal_api_key", "jwt", "impersonation")]
    )
    def test_actions_require_non_impersonated_session(self, action: str, auth: str) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        key = self._create_key(User.objects.create_and_join(self.organization, "member@example.com", None))
        url = self._action_url(key, action)
        if auth == "impersonation":
            staff = User.objects.create(email="staff@example.com", is_staff=True)
            session = self.client.session
            session[loginas_settings.USER_SESSION_FLAG] = TimestampSigner().sign(str(staff.pk))
            session.save()
            assert self.client.get(self._url()).status_code == status.HTTP_200_OK
            response = self.client.post(url)
        else:
            if auth == "jwt":
                token = encode_jwt({"id": self.user.id}, timedelta(minutes=5), PosthogJwtAudience.IMPERSONATED_USER)
            else:
                token = generate_random_token_personal()
                self._create_key(self.user, value=token, scopes=["*"])
            self.client.logout()
            if auth == "jwt":
                assert self.client.get(self._url(), HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 200
            response = self.client.post(url, HTTP_AUTHORIZATION=f"Bearer {token}")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert PersonalAPIKey.objects.get(pk=key.pk).secure_value == key.secure_value

    @parameterized.expand([("roll", "rolled"), ("revoke", "deleted")])
    @patch.object(send_personal_api_keys_changed_by_org_admin, "delay")
    def test_owner_gets_email_with_change(self, action: str, expected_outcome: str, mock_delay: MagicMock) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        owner = self._create_owner_in_other_orgs()
        key = self._create_scoped_key(owner, (), ("O", "B"), label="ci-key")

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._action_url(key, action))

        assert response.status_code == status.HTTP_200_OK, response.content
        rolled_key = PersonalAPIKey.objects.filter(pk=key.pk).first()
        mock_delay.assert_called_once_with(
            user_id=owner.id,
            organization_id=str(self.organization.id),
            changes=[
                {
                    "label": "ci-key",
                    "mask_value": rolled_key.mask_value if rolled_key else key.mask_value,
                    "outcome": expected_outcome,
                }
            ],
        )

    @parameterized.expand([("roll",), ("revoke",)])
    @patch.object(
        send_personal_api_keys_changed_by_org_admin, "delay", side_effect=ConnectionError("broker unavailable")
    )
    def test_email_dispatch_failure_preserves_successful_key_action(self, action: str, _mock_delay: MagicMock) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        key = self._create_key(User.objects.create_and_join(self.organization, "member@example.com", None))
        old_secret = key.secure_value

        with self.assertLogs(level="ERROR"), self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._action_url(key, action))

        assert response.status_code == status.HTTP_200_OK, response.content
        if action == "roll":
            key.refresh_from_db()
            assert key.secure_value != old_secret
        else:
            assert not PersonalAPIKey.objects.filter(pk=key.pk).exists()
