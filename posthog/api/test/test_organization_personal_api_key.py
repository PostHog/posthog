from datetime import datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.api.organization_personal_api_key_actions import OrganizationPersonalAPIKeyActions
from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.utils import generate_random_token_personal, hash_key_value, mask_key_value
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

    def _bulk_action_url(self, action: str) -> str:
        return f"{self._url()}{action}/"

    def _key_state(self, key: PersonalAPIKey) -> str:
        current = PersonalAPIKey.objects.filter(pk=key.pk).first()
        if current is None:
            return "deleted"
        changes = []
        if current.secure_value != key.secure_value:
            changes.append("rolled")
        if (current.scoped_teams, current.scoped_organizations) != (key.scoped_teams, key.scoped_organizations):
            changes.append("access_removed")
        return " and ".join(changes) or "untouched"

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
            ("unscoped", (), (), None, ("B",)),
            ("org_scoped", (), ("O", "B"), None, ("B",)),
            ("team_scoped", ("O", "B"), (), ("B",), None),
            ("team_and_org_scoped", ("O", "B"), ("O", "B"), ("B",), ("B",)),
        ]
    )
    def test_revoke_removes_only_this_org(
        self,
        _name: str,
        team_refs: tuple[str, ...],
        org_refs: tuple[str, ...],
        expected_team_refs: tuple[str, ...] | None,
        expected_org_refs: tuple[str, ...] | None,
    ) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        owner = self._create_owner_in_other_orgs()
        old_value = generate_random_token_personal()
        key = self._create_scoped_key(owner, team_refs, org_refs, value=old_value, scopes=["user:read"])
        self.client.logout()
        assert self.client.get("/api/users/@me/", HTTP_AUTHORIZATION=f"Bearer {old_value}").status_code == 200
        self.client.force_login(self.user)

        response = self.client.post(self._action_url(key, "revoke"))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"outcome": "access_removed"}
        key.refresh_from_db()
        assert key.scoped_teams == (
            None if expected_team_refs is None else [self.team_refs[ref] for ref in expected_team_refs]
        )
        assert key.scoped_organizations == (
            None if expected_org_refs is None else [self.org_refs[ref] for ref in expected_org_refs]
        )
        assert key.id not in {row["id"] for row in self.client.get(self._url()).json()["results"]}
        self.client.logout()
        response = self.client.get("/api/users/@me/", HTTP_AUTHORIZATION=f"Bearer {old_value}")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @parameterized.expand(
        [
            ("unscoped_owner_only_in_o", False, (), ()),
            ("org_scoped_to_o", True, (), ("O",)),
            ("org_scoped_to_o_and_left_c", True, (), ("O", "C")),
            ("teams_o_b_orgs_o", True, ("O", "B"), ("O",)),
            ("teams_o_orgs_o_b", True, ("O",), ("O", "B")),
            ("teams_o_and_deleted_team", False, ("O", "deleted"), ()),
        ]
    )
    def test_revoke_deletes_when_no_other_live_reach(
        self, _name: str, owner_joins_b: bool, team_refs: tuple[str, ...], org_refs: tuple[str, ...]
    ) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        owner = self._create_owner_in_other_orgs(owner_joins_b=owner_joins_b)
        key = self._create_scoped_key(owner, team_refs, org_refs)

        response = self.client.post(self._action_url(key, "revoke"))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"outcome": "deleted"}
        assert not PersonalAPIKey.objects.filter(pk=key.pk).exists()

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

    @parameterized.expand(
        [
            ("roll", "roll", ("O",)),
            ("revoke_delete", "revoke", ("O",)),
            ("revoke_detach", "revoke", ("O", "B")),
        ]
    )
    @patch("posthog.tasks.team_access_cache_tasks.invalidate_token_sync")
    def test_actions_invalidate_auth_cache(
        self, _name: str, action: str, org_refs: tuple[str, ...], mock_invalidate: MagicMock
    ) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        owner = self._create_owner_in_other_orgs()
        key = self._create_scoped_key(owner, (), org_refs)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._action_url(key, action))

        assert response.status_code == status.HTTP_200_OK, response.content
        mock_invalidate.assert_any_call(key.secure_value)

    @parameterized.expand(
        [
            ("roll", "roll", ("O", "B"), ["updated"], "updated"),
            ("revoke_delete", "revoke", ("O",), ["deleted"], None),
            ("revoke_detach", "revoke", ("O", "B"), ["revoked", "updated"], "updated"),
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
            # Listed for O because it holds O's team, but its organization limit leaves O out.
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

    @parameterized.expand([("roll", True), ("revoke", True), ("roll_all", False), ("revoke_all", False)])
    def test_actions_require_recent_authentication(self, action: str, detail: bool) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        key = self._create_key(User.objects.create_and_join(self.organization, "member@example.com", None))
        url = self._action_url(key, action) if detail else self._bulk_action_url(action)

        with time_machine.travel(
            datetime.now() + timedelta(seconds=settings.SESSION_SENSITIVE_ACTIONS_AGE + 10), tick=False
        ):
            response = self.client.post(url)
            list_response = self.client.get(self._url())

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.json()["code"] == "sensitive_action_required_reauth"
        assert list_response.status_code == status.HTTP_200_OK, list_response.content

    @parameterized.expand([("roll", True), ("revoke", True), ("roll_all", False), ("revoke_all", False)])
    def test_actions_reject_personal_api_key_auth(self, action: str, detail: bool) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        admin_value = generate_random_token_personal()
        self._create_key(self.user, value=admin_value, scopes=["*"])
        key = self._create_key(User.objects.create_and_join(self.organization, "member@example.com", None))
        url = self._action_url(key, action) if detail else self._bulk_action_url(action)
        self.client.logout()

        response = self.client.post(url, HTTP_AUTHORIZATION=f"Bearer {admin_value}")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert PersonalAPIKey.objects.get(pk=key.pk).secure_value == key.secure_value

    @parameterized.expand([("delete", ("O",), "deleted"), ("detach", ("O", "B"), "access_removed")])
    @patch.object(send_personal_api_keys_changed_by_org_admin, "delay")
    def test_owner_gets_email_with_change(
        self, _name: str, org_refs: tuple[str, ...], expected_outcome: str, mock_delay: MagicMock
    ) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        owner = self._create_owner_in_other_orgs()
        key = self._create_scoped_key(owner, (), org_refs, label="ci-key")

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._action_url(key, "revoke"))

        assert response.status_code == status.HTTP_200_OK, response.content
        mock_delay.assert_called_once_with(
            user_id=owner.id,
            organization_id=str(self.organization.id),
            acting_user_email=self.user.email,
            changes=[{"label": "ci-key", "mask_value": key.mask_value, "outcome": expected_outcome}],
        )

    @parameterized.expand(
        [
            (
                "roll_all",
                {"rolled": 4, "deleted": 0, "access_removed": 0},
                {
                    "single_org": "rolled",
                    "multi_org": "rolled",
                    "admin_org_scoped": "rolled",
                    "teams_o_b": "rolled",
                    "outsider": "untouched",
                },
            ),
            (
                "revoke_all",
                {"rolled": 0, "deleted": 2, "access_removed": 2},
                {
                    "single_org": "deleted",
                    "multi_org": "rolled and access_removed",
                    "admin_org_scoped": "deleted",
                    "teams_o_b": "rolled and access_removed",
                    "outsider": "untouched",
                },
            ),
        ]
    )
    def test_bulk_actions_cover_every_key(
        self, action: str, expected_counts: dict[str, int], expected_states: dict[str, str]
    ) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        owner = self._create_owner_in_other_orgs()
        single_org_member = User.objects.create_and_join(self.organization, "single-org@example.com", None)
        outsider_org = Organization.objects.create(name="bulk-outsider-org-5d1f7b")
        outsider = User.objects.create_and_join(outsider_org, "bulk-outsider@example.com", None)
        keys = {
            "single_org": self._create_key(single_org_member),
            "multi_org": self._create_scoped_key(owner, (), ()),
            "admin_org_scoped": self._create_scoped_key(self.user, (), ("O",)),
            "teams_o_b": self._create_scoped_key(owner, ("O", "B"), ()),
            "outsider": self._create_key(outsider),
        }

        response = self.client.post(self._bulk_action_url(action))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == expected_counts
        assert {name: self._key_state(key) for name, key in keys.items()} == expected_states

    @patch.object(send_personal_api_keys_changed_by_org_admin, "delay")
    def test_bulk_action_sends_one_email_per_owner(self, mock_delay: MagicMock) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        owner = User.objects.create_and_join(self.organization, "two-keys@example.com", None)
        other_owner = User.objects.create_and_join(self.organization, "one-key@example.com", None)
        first_key = self._create_key(owner, label="first-key")
        second_key = self._create_key(owner, label="second-key")
        other_key = self._create_key(other_owner, label="other-key")

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self._bulk_action_url("roll_all"))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert len(mock_delay.call_args_list) == 2
        calls_by_owner = {
            call.kwargs["user_id"]: {
                **call.kwargs,
                "changes": sorted(call.kwargs["changes"], key=lambda change: change["label"]),
            }
            for call in mock_delay.call_args_list
        }
        common = {"organization_id": str(self.organization.id), "acting_user_email": self.user.email}
        assert calls_by_owner == {
            owner.id: {
                **common,
                "user_id": owner.id,
                "changes": [
                    {"label": "first-key", "mask_value": first_key.mask_value, "outcome": "rolled"},
                    {"label": "second-key", "mask_value": second_key.mask_value, "outcome": "rolled"},
                ],
            },
            other_owner.id: {
                **common,
                "user_id": other_owner.id,
                "changes": [{"label": "other-key", "mask_value": other_key.mask_value, "outcome": "rolled"}],
            },
        }

    @parameterized.expand(
        [
            ("roll_all", {"rolled": 1, "deleted": 0, "access_removed": 0}),
            ("revoke_all", {"rolled": 0, "deleted": 1, "access_removed": 0}),
        ]
    )
    def test_bulk_action_skips_key_that_left_org(self, action: str, expected_counts: dict[str, int]) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        owner = self._create_owner_in_other_orgs()
        self._create_key(User.objects.create_and_join(self.organization, "single-org@example.com", None))
        leaving_key = self._create_scoped_key(owner, (), ("O", "B"))
        real_lock = OrganizationPersonalAPIKeyActions._lock
        locked_key_ids: list[str] = []

        def rescope_then_lock(key_id: str) -> PersonalAPIKey | None:
            locked_key_ids.append(key_id)
            if key_id == leaving_key.id:
                PersonalAPIKey.objects.filter(pk=key_id).update(scoped_organizations=[self.org_refs["B"]])
            return real_lock(key_id)

        with patch.object(OrganizationPersonalAPIKeyActions, "_lock", side_effect=rescope_then_lock):
            response = self.client.post(self._bulk_action_url(action))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == expected_counts
        assert leaving_key.id in locked_key_ids
        after = PersonalAPIKey.objects.get(pk=leaving_key.pk)
        assert (after.secure_value, after.scoped_teams, after.scoped_organizations) == (
            leaving_key.secure_value,
            None,
            [self.org_refs["B"]],
        )

    @patch.object(send_personal_api_keys_changed_by_org_admin, "delay")
    def test_bulk_action_emails_owners_of_keys_changed_before_a_failure(self, mock_delay: MagicMock) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        keys = {}
        for email in ("first-owner@example.com", "second-owner@example.com"):
            key = self._create_key(User.objects.create_and_join(self.organization, email, None), label=email)
            keys[key.id] = key
        real_lock = OrganizationPersonalAPIKeyActions._lock
        locked_key_ids: list[str] = []

        def fail_on_second_key(key_id: str) -> PersonalAPIKey | None:
            locked_key_ids.append(key_id)
            if len(locked_key_ids) == 2:
                raise RuntimeError("lock failed")
            return real_lock(key_id)

        with (
            self.captureOnCommitCallbacks(execute=True),
            patch.object(OrganizationPersonalAPIKeyActions, "_lock", side_effect=fail_on_second_key),
        ):
            response = self.client.post(self._bulk_action_url("revoke_all"))

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR, response.content
        changed_key, failed_key = keys[locked_key_ids[0]], keys[locked_key_ids[1]]
        mock_delay.assert_called_once_with(
            user_id=changed_key.user_id,
            organization_id=str(self.organization.id),
            acting_user_email=self.user.email,
            changes=[{"label": changed_key.label, "mask_value": changed_key.mask_value, "outcome": "deleted"}],
        )
        assert {name: self._key_state(key) for name, key in [("changed", changed_key), ("failed", failed_key)]} == {
            "changed": "deleted",
            "failed": "untouched",
        }
