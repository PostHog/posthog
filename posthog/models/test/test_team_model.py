from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError

from parameterized import parameterized

from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from ee.models.explicit_team_membership import ExplicitTeamMembership
from ee.models.rbac.access_control import AccessControl
from ee.models.rbac.role import Role, RoleMembership


class TestTeamCoreEventsConfig(BaseTest):
    @parameterized.expand(
        [
            (
                "event goal",
                {
                    "id": "goal-1",
                    "name": "Purchase",
                    "category": "monetization",
                    "filter": {"kind": "EventsNode", "event": "$purchase"},
                },
            ),
            (
                "action goal",
                {
                    "id": "goal-2",
                    "name": "Signup Action",
                    "category": "activation",
                    "filter": {"kind": "ActionsNode", "id": 123},
                },
            ),
            (
                "data warehouse goal",
                {
                    "id": "goal-3",
                    "name": "Stripe Charges",
                    "category": "monetization",
                    "filter": {
                        "kind": "DataWarehouseNode",
                        "id": "stripe_charges",
                        "table_name": "stripe_charges",
                        "timestamp_field": "created_at",
                        "distinct_id_field": "customer_email",
                        "id_field": "id",
                    },
                },
            ),
            (
                "event goal with math sum",
                {
                    "id": "goal-4",
                    "name": "Revenue",
                    "category": "monetization",
                    "filter": {
                        "kind": "EventsNode",
                        "event": "purchase",
                        "math": "sum",
                        "math_property": "revenue",
                    },
                },
            ),
        ]
    )
    def test_core_events_valid(self, _name: str, event: dict):
        config = self.team.core_events_config
        config.core_events = [event]
        config.save()
        config.refresh_from_db()

        events = config.core_events
        assert len(events) == 1
        assert events[0]["id"] == event["id"]
        assert events[0]["name"] == event["name"]

    def test_core_events_empty_by_default(self):
        assert self.team.core_events_config.core_events == []

    def test_core_events_missing_filter_raises(self):
        with self.assertRaises(ValidationError):
            config = self.team.core_events_config
            config.core_events = [
                {
                    "id": "goal-1",
                    "name": "Bad Goal",
                    "category": "monetization",
                    # missing filter
                }
            ]

    def test_core_events_missing_category_raises(self):
        with self.assertRaises(ValidationError):
            config = self.team.core_events_config
            config.core_events = [
                {
                    "id": "goal-1",
                    "name": "Bad Goal",
                    "filter": {"kind": "EventsNode", "event": "purchase"},
                    # missing category
                }
            ]

    def test_core_events_all_events_not_allowed(self):
        """All events (empty event name) should not be allowed as a core event."""
        with self.assertRaises(ValidationError) as context:
            config = self.team.core_events_config
            config.core_events = [
                {
                    "id": "goal-1",
                    "name": "All Events Goal",
                    "category": "monetization",
                    "filter": {"kind": "EventsNode", "event": None},
                }
            ]
        assert "All events" in str(context.exception)

    def test_core_events_empty_event_name_not_allowed(self):
        """Empty event name should not be allowed as a core event."""
        with self.assertRaises(ValidationError) as context:
            config = self.team.core_events_config
            config.core_events = [
                {
                    "id": "goal-1",
                    "name": "Empty Event Goal",
                    "category": "monetization",
                    "filter": {"kind": "EventsNode", "event": ""},
                }
            ]
        assert "All events" in str(context.exception)


class TestTeam(BaseTest):
    def test_all_users_with_access_simple_org_membership(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        another_user = User.objects.create_and_join(self.organization, "test2@posthog.com", None)

        all_user_with_access_ids = list(self.team.all_users_with_access().values_list("id", flat=True))

        assert sorted(all_user_with_access_ids) == sorted([self.user.id, another_user.id])

    def test_all_users_with_access_simple_org_membership_and_redundant_team_one(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        another_user = User.objects.create_and_join(self.organization, "test2@posthog.com", None)
        ExplicitTeamMembership.objects.create(team=self.team, parent_membership=self.organization_membership)

        all_user_with_access_ids = list(self.team.all_users_with_access().values_list("id", flat=True))

        assert sorted(all_user_with_access_ids) == sorted(
            [self.user.id, another_user.id]
        )  # self.user should only be listed once

    def test_all_users_with_access_new_access_control_non_private_team(self):
        """Test that all organization members have access to a non-private team with the new access control system"""

        # Create another user as a member
        member_user = User.objects.create_and_join(
            self.organization,
            email="member@posthog.com",
            first_name="first_name",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )

        # Get all users with access
        all_user_with_access_ids = list(self.team.all_users_with_access().values_list("id", flat=True))

        # Both users should have access since the team is not private
        assert sorted(all_user_with_access_ids) == sorted([self.user.id, member_user.id])

    def test_all_users_with_access_new_access_control_private_team(self):
        """Test that only users with specific access have access to a private team with the new access control system"""

        # Make the team private
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        # Create another user as a member
        User.objects.create_and_join(
            self.organization,
            email="member@posthog.com",
            first_name="first_name",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )

        # Set the original user as admin
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Get all users with access
        all_user_with_access_ids = list(self.team.all_users_with_access().values_list("id", flat=True))

        # Only the admin user should have access
        assert all_user_with_access_ids == [self.user.id]

    def test_all_users_with_access_new_access_control_private_team_with_member_access(self):
        """Test that users with specific member access have access to a private team with the new access control system"""

        # Make the team private
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        # Create another user as a member
        member_user = User.objects.create_and_join(
            self.organization,
            email="member@posthog.com",
            first_name="first_name",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )
        member_org_membership = OrganizationMembership.objects.get(organization=self.organization, user=member_user)

        # Give the member user access to the team
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=member_org_membership,
            access_level="member",
        )

        # Set the original user as admin
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Get all users with access
        all_user_with_access_ids = list(self.team.all_users_with_access().values_list("id", flat=True))

        # Both users should have access
        assert sorted(all_user_with_access_ids) == sorted([self.user.id, member_user.id])

    def test_all_users_with_access_new_access_control_private_team_with_role_access(self):
        """Test that users with role-based access have access to a private team with the new access control system"""

        # Make the team private
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        # Create another user as a member
        member_user = User.objects.create_and_join(
            self.organization,
            email="member@posthog.com",
            first_name="first_name",
            password=None,
            level=OrganizationMembership.Level.MEMBER,
        )
        member_org_membership = OrganizationMembership.objects.get(organization=self.organization, user=member_user)

        # Create a role
        role = Role.objects.create(name="Test Role", organization=self.organization)

        # Assign the member to the role
        RoleMembership.objects.create(role=role, user=member_user, organization_member=member_org_membership)

        # Give the role access to the team
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), role=role, access_level="member"
        )

        # Set the original user as admin
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Get all users with access
        all_user_with_access_ids = list(self.team.all_users_with_access().values_list("id", flat=True))

        # Both users should have access
        assert sorted(all_user_with_access_ids) == sorted([self.user.id, member_user.id])
