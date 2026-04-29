from posthog.test.base import BaseTest

from rest_framework import exceptions

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.models.user import User
from posthog.rbac.guest_grants import (
    GUEST_VIEWER_ACCESS_LEVEL,
    apply_invite_grants,
    create_grant,
    promote_to_member,
    revoke_grants_for_membership,
    validate_invite_grants,
)

from products.notebooks.backend.models import Notebook

from ee.models.rbac.access_control import AccessControl


class TestGuestGrants(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}
        ]
        self.organization.save()

        self.guest_user = User.objects.create_user(
            email="guest@example.com", first_name="Guest", password="password123"
        )
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )
        self.notebook = Notebook.objects.create(team=self.team, title="N", short_id="NBK00001")

    def test_create_grant_writes_ac_row_at_viewer_by_default(self) -> None:
        ac = create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="notebook",
            resource_id=self.notebook.short_id,
            created_by=self.user,
        )

        self.assertEqual(ac.resource, "notebook")
        self.assertEqual(ac.resource_id, str(self.notebook.pk))
        self.assertEqual(ac.access_level, GUEST_VIEWER_ACCESS_LEVEL)
        self.assertEqual(ac.organization_member, self.guest_membership)

    def test_create_grant_writes_ac_row_at_editor_when_requested(self) -> None:
        ac = create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="notebook",
            resource_id=self.notebook.short_id,
            created_by=self.user,
            access_level="editor",
        )

        self.assertEqual(ac.access_level, "editor")

    def test_create_grant_rejects_invalid_access_level(self) -> None:
        with self.assertRaises(exceptions.ValidationError):
            create_grant(
                membership=self.guest_membership,
                team=self.team,
                resource="notebook",
                resource_id=self.notebook.short_id,
                created_by=self.user,
                access_level="manager",
            )

    def test_create_grant_rejects_unknown_resource(self) -> None:
        with self.assertRaises(exceptions.ValidationError):
            create_grant(
                membership=self.guest_membership,
                team=self.team,
                resource="dashboard",
                resource_id="1",
                created_by=self.user,
            )

    def test_revoke_deletes_all_ac_rows_for_membership(self) -> None:
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="notebook",
            resource_id=self.notebook.short_id,
            created_by=self.user,
        )
        other_notebook = Notebook.objects.create(team=self.team, title="O", short_id="NBK00002")
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="notebook",
            resource_id=other_notebook.short_id,
            created_by=self.user,
        )

        removed = revoke_grants_for_membership(self.guest_membership)

        self.assertGreaterEqual(removed, 2)
        self.assertFalse(AccessControl.objects.filter(organization_member=self.guest_membership).exists())

    def test_promote_to_member_revokes_ac_and_flips_flag(self) -> None:
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="notebook",
            resource_id=self.notebook.short_id,
            created_by=self.user,
        )

        removed = promote_to_member(self.guest_membership, by=self.user)
        self.guest_membership.refresh_from_db()

        self.assertGreaterEqual(removed, 1)
        self.assertFalse(self.guest_membership.is_guest)
        self.assertFalse(self.guest_membership.bypass_sso)
        self.assertFalse(AccessControl.objects.filter(organization_member=self.guest_membership).exists())

    def test_promote_to_member_rejects_non_guest(self) -> None:
        regular = OrganizationMembership.objects.get(organization=self.organization, user=self.user)
        with self.assertRaises(exceptions.ValidationError):
            promote_to_member(regular, by=self.user)

    def test_apply_invite_grants_creates_ac_rows_for_each_entry(self) -> None:
        notebook_short_id = self.notebook.short_id
        team_pk = self.team.pk
        invite_user = self.user

        class _FakeInvite:
            guest_resources = [
                {"team_id": team_pk, "resource": "notebook", "resource_id": notebook_short_id},
            ]
            created_by = invite_user

        created = apply_invite_grants(_FakeInvite(), self.guest_membership)
        self.assertEqual(len(created), 1)
        self.assertTrue(
            AccessControl.objects.filter(
                organization_member=self.guest_membership,
                resource="notebook",
                resource_id=str(self.notebook.pk),
                access_level=GUEST_VIEWER_ACCESS_LEVEL,
            ).exists()
        )

    def test_apply_invite_grants_respects_per_entry_access_level(self) -> None:
        notebook_short_id = self.notebook.short_id
        team_pk = self.team.pk
        invite_user = self.user

        class _FakeInvite:
            guest_resources = [
                {
                    "team_id": team_pk,
                    "resource": "notebook",
                    "resource_id": notebook_short_id,
                    "access_level": "editor",
                },
            ]
            created_by = invite_user

        apply_invite_grants(_FakeInvite(), self.guest_membership)
        ac = AccessControl.objects.get(
            organization_member=self.guest_membership,
            resource="notebook",
            resource_id=str(self.notebook.pk),
        )
        self.assertEqual(ac.access_level, "editor")

    def test_validate_invite_grants_requires_access_control_feature(self) -> None:
        self.organization.available_product_features = []
        self.organization.save()
        with self.assertRaises(exceptions.ValidationError):
            validate_invite_grants(
                self.organization,
                [{"team_id": self.team.pk, "resource": "notebook", "resource_id": self.notebook.short_id}],
            )

    def test_validate_invite_grants_rejects_unknown_team(self) -> None:
        with self.assertRaises(exceptions.ValidationError):
            validate_invite_grants(
                self.organization,
                [{"team_id": 99999, "resource": "notebook", "resource_id": self.notebook.short_id}],
            )

    def test_validate_invite_grants_rejects_unknown_resource_type(self) -> None:
        with self.assertRaises(exceptions.ValidationError):
            validate_invite_grants(
                self.organization,
                [{"team_id": self.team.pk, "resource": "dashboard", "resource_id": "1"}],
            )

    def test_validate_invite_grants_rejects_missing_resource_id(self) -> None:
        with self.assertRaises(exceptions.ValidationError):
            validate_invite_grants(
                self.organization,
                [{"team_id": self.team.pk, "resource": "notebook", "resource_id": "ZZZZZZZZ"}],
            )

    def test_validate_invite_grants_requires_at_least_one_entry(self) -> None:
        with self.assertRaises(exceptions.ValidationError):
            validate_invite_grants(self.organization, [])
