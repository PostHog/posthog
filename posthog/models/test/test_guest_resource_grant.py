from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from parameterized import parameterized

from posthog.models import GuestResourceGrant, OrganizationInvite, OrganizationMembership, User
from posthog.models.team.team import Team


class TestGuestResourceGrant(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_user = User.objects.create_user(email="guest@example.com", password="password", first_name="Guest")
        self.other_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.other_user,
            is_guest=True,
        )
        self.second_team = Team.objects.create(organization=self.organization, name="Second team")

    @parameterized.expand(
        [
            ("dashboard_with_pk", "dashboard", "42"),
            ("insight_with_short_id", "insight", "WMIhED1b"),
            ("notebook_with_short_id", "notebook", "abc-123-def"),
        ]
    )
    def test_grant_with_valid_resource_persists(self, _name, resource: str, resource_id: str) -> None:
        grant = GuestResourceGrant.objects.create(
            organization_membership=self.other_membership,
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            created_by=self.user,
        )

        grant.refresh_from_db()
        self.assertEqual(grant.resource, resource)
        self.assertEqual(grant.resource_id, resource_id)
        self.assertEqual(grant.organization_membership_id, self.other_membership.id)

    def test_grant_without_membership_violates_not_null(self) -> None:
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GuestResourceGrant.objects.create(
                    organization_membership=None,
                    team=self.team,
                    resource=GuestResourceGrant.Resource.DASHBOARD,
                    resource_id="1",
                )

    def test_duplicate_grant_tuple_raises(self) -> None:
        GuestResourceGrant.objects.create(
            organization_membership=self.other_membership,
            team=self.team,
            resource=GuestResourceGrant.Resource.INSIGHT,
            resource_id="short1",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GuestResourceGrant.objects.create(
                    organization_membership=self.other_membership,
                    team=self.team,
                    resource=GuestResourceGrant.Resource.INSIGHT,
                    resource_id="short1",
                )

    def test_same_resource_id_allowed_across_different_teams(self) -> None:
        GuestResourceGrant.objects.create(
            organization_membership=self.other_membership,
            team=self.team,
            resource=GuestResourceGrant.Resource.DASHBOARD,
            resource_id="7",
        )
        GuestResourceGrant.objects.create(
            organization_membership=self.other_membership,
            team=self.second_team,
            resource=GuestResourceGrant.Resource.DASHBOARD,
            resource_id="7",
        )

        self.assertEqual(
            GuestResourceGrant.objects.filter(organization_membership=self.other_membership).count(),
            2,
        )

    def test_related_name_resolves_from_membership(self) -> None:
        GuestResourceGrant.objects.create(
            organization_membership=self.other_membership,
            team=self.team,
            resource=GuestResourceGrant.Resource.DASHBOARD,
            resource_id="1",
        )
        GuestResourceGrant.objects.create(
            organization_membership=self.other_membership,
            team=self.team,
            resource=GuestResourceGrant.Resource.NOTEBOOK,
            resource_id="note-1",
        )

        self.assertEqual(self.other_membership.guest_resource_grants.count(), 2)


class TestGuestMembershipLevelConstraint(BaseTest):
    def test_guest_member_level_is_allowed(self) -> None:
        user = User.objects.create_user(email="gm@example.com", password="pw", first_name="G")
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=user,
            is_guest=True,
            level=OrganizationMembership.Level.MEMBER,
        )

    @parameterized.expand(
        [
            ("admin", OrganizationMembership.Level.ADMIN),
            ("owner", OrganizationMembership.Level.OWNER),
        ]
    )
    def test_guest_with_non_member_level_violates_constraint(self, _name, level) -> None:
        user = User.objects.create_user(email=f"gl-{_name}@example.com", password="pw", first_name="G")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OrganizationMembership.objects.create(
                    organization=self.organization,
                    user=user,
                    is_guest=True,
                    level=level,
                )


class TestRegularMembersManager(BaseTest):
    def test_regular_manager_excludes_guests(self) -> None:
        guest_user = User.objects.create_user(email="guest2@example.com", password="pw", first_name="G")
        regular_user = User.objects.create_user(email="regular@example.com", password="pw", first_name="R")
        OrganizationMembership.objects.create(organization=self.organization, user=guest_user, is_guest=True)
        OrganizationMembership.objects.create(organization=self.organization, user=regular_user, is_guest=False)

        org_memberships = OrganizationMembership.objects.filter(organization=self.organization)
        regular_memberships = OrganizationMembership.regular.filter(organization=self.organization)

        self.assertTrue(org_memberships.filter(user=guest_user).exists())
        self.assertFalse(regular_memberships.filter(user=guest_user).exists())
        self.assertTrue(regular_memberships.filter(user=regular_user).exists())


class TestIsGuestInvite(BaseTest):
    def test_empty_guest_resources_is_regular_invite(self) -> None:
        invite = OrganizationInvite.objects.create(organization=self.organization, target_email="a@example.com")
        self.assertFalse(invite.is_guest_invite)

    def test_non_empty_guest_resources_is_guest_invite(self) -> None:
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="b@example.com",
            guest_resources=[{"team_id": self.team.id, "resource": "dashboard", "resource_id": "1"}],
        )
        self.assertTrue(invite.is_guest_invite)

    def test_bypass_sso_default_is_false(self) -> None:
        invite = OrganizationInvite.objects.create(organization=self.organization, target_email="c@example.com")
        self.assertFalse(invite.bypass_sso)

    def test_bypass_sso_persists(self) -> None:
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="d@example.com",
            bypass_sso=True,
            guest_resources=[{"team_id": self.team.id, "resource": "dashboard", "resource_id": "1"}],
        )
        invite.refresh_from_db()
        self.assertTrue(invite.bypass_sso)

    def test_bypass_sso_without_guest_resources_violates_constraint(self) -> None:
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OrganizationInvite.objects.create(
                    organization=self.organization,
                    target_email="f@example.com",
                    bypass_sso=True,
                )

    def test_guest_resources_persists_list_of_dicts(self) -> None:
        resources = [
            {"team_id": self.team.id, "resource": "dashboard", "resource_id": "1"},
            {"team_id": self.team.id, "resource": "insight", "resource_id": "short-id"},
        ]
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="e@example.com",
            guest_resources=resources,
        )
        invite.refresh_from_db()
        self.assertEqual(invite.guest_resources, resources)
