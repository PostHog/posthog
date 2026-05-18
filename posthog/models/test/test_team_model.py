from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.core_event import CoreEvent
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from ee.models.explicit_team_membership import ExplicitTeamMembership
from ee.models.rbac.access_control import AccessControl
from ee.models.rbac.role import Role, RoleMembership


class TestCoreEvent(BaseTest):
    @parameterized.expand(
        [
            (
                "event goal",
                "Purchase",
                "monetization",
                {"kind": "EventsNode", "event": "$purchase"},
            ),
            (
                "action goal",
                "Signup Action",
                "activation",
                {"kind": "ActionsNode", "id": 123},
            ),
            (
                "data warehouse goal",
                "Stripe Charges",
                "monetization",
                {
                    "kind": "DataWarehouseNode",
                    "id": "stripe_charges",
                    "table_name": "stripe_charges",
                    "timestamp_field": "created_at",
                    "distinct_id_field": "customer_email",
                    "id_field": "id",
                },
            ),
            (
                "event goal with math sum",
                "Revenue",
                "monetization",
                {
                    "kind": "EventsNode",
                    "event": "purchase",
                    "math": "sum",
                    "math_property": "revenue",
                },
            ),
        ]
    )
    def test_core_events_valid(self, _name: str, name: str, category: str, filter: dict):
        core_event = CoreEvent.objects.create(
            team=self.team,
            name=name,
            category=category,
            filter=filter,
        )
        core_event.refresh_from_db()

        assert core_event.name == name
        assert core_event.category == category
        assert core_event.filter == filter

    def test_core_events_empty_by_default(self):
        assert self.team.core_events.count() == 0

    def test_core_events_missing_filter_raises(self):
        with self.assertRaises(ValidationError):
            CoreEvent.objects.create(
                team=self.team,
                name="Bad Goal",
                category="monetization",
                filter=None,
            )

    def test_core_events_invalid_filter_kind_raises(self):
        with self.assertRaises(ValidationError):
            CoreEvent.objects.create(
                team=self.team,
                name="Bad Goal",
                category="monetization",
                filter={"kind": "InvalidNode"},
            )

    def test_core_events_all_events_not_allowed(self):
        """All events (empty event name) should not be allowed as a core event."""
        with self.assertRaises(ValidationError) as context:
            CoreEvent.objects.create(
                team=self.team,
                name="All Events Goal",
                category="monetization",
                filter={"kind": "EventsNode", "event": None},
            )
        assert "All events" in str(context.exception)

    def test_core_events_empty_event_name_not_allowed(self):
        """Empty event name should not be allowed as a core event."""
        with self.assertRaises(ValidationError) as context:
            CoreEvent.objects.create(
                team=self.team,
                name="Empty Event Goal",
                category="monetization",
                filter={"kind": "EventsNode", "event": ""},
            )
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


class TestTeamSetTokenAndSave(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.api_token = "phc_old_token_value"
        self.team.save()

    @parameterized.expand(
        [
            ("empty", "", "non-empty"),
            ("whitespace_only", "   ", "non-empty"),
            ("too_long", "a" * 201, "200 characters"),
            ("identical", "phc_old_token_value", "identical"),
        ]
    )
    def test_set_token_and_save_validation_rejects_invalid(self, _name: str, new_token: str, message_fragment: str):
        with self.assertRaises(ValueError) as ctx:
            self.team.set_token_and_save(
                new_token=new_token,
                user=self.user,
                is_impersonated_session=False,
            )
        assert message_fragment in str(ctx.exception)
        self.team.refresh_from_db()
        assert self.team.api_token == "phc_old_token_value"

    @patch("posthog.tasks.integrations.push_vercel_secrets.delay")
    @patch("posthog.models.team.team.set_team_in_cache")
    def test_set_token_and_save_success_runs_full_side_effect_chain(self, mock_set_cache, mock_push_vercel) -> None:
        self.team.set_token_and_save(
            new_token="phc_new_token_value",
            user=self.user,
            is_impersonated_session=False,
        )

        self.team.refresh_from_db()
        assert self.team.api_token == "phc_new_token_value"

        cache_calls = [call.args for call in mock_set_cache.call_args_list]
        assert ("phc_old_token_value", None) in cache_calls
        assert any(args[0] == "phc_new_token_value" and args[1] is self.team for args in cache_calls)

        mock_push_vercel.assert_called_once_with(self.team.id)

        log_entry = ActivityLog.objects.get(scope="Team", item_id=str(self.team.pk), activity="updated")
        assert log_entry.detail is not None
        change = log_entry.detail["changes"][0]
        assert change["field"] == "api_token"
        assert change["before"] == "phc_old_token_value"
        assert change["after"] == "phc_new_token_value"

    def test_set_token_and_save_rejects_token_already_taken_by_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, api_token="phc_already_taken")

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.team.set_token_and_save(
                new_token="phc_already_taken",
                user=self.user,
                is_impersonated_session=False,
            )

        other_team.refresh_from_db()
        assert other_team.api_token == "phc_already_taken"
        self.team.refresh_from_db()
        assert self.team.api_token == "phc_old_token_value"

    def test_set_token_and_save_strips_whitespace(self) -> None:
        self.team.set_token_and_save(
            new_token="  phc_trimmed  ",
            user=self.user,
            is_impersonated_session=False,
        )
        self.team.refresh_from_db()
        assert self.team.api_token == "phc_trimmed"
