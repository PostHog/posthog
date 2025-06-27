from posthog.models.user_group import UserGroup, UserGroupMembership
from ee.models.rbac.role import Role, RoleMembership
from django.core.management import call_command
from posthog.test.base import BaseTest
from posthog.models.error_tracking import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingAssignmentRule,
    ErrorTrackingGroupingRule,
)


class TestMigrateUserGroupsToRoles(BaseTest):
    def test_migrates_group_and_members_to_roles(self):
        user_group = UserGroup.objects.create(team=self.team, name="Test group")
        UserGroupMembership.objects.create(group=user_group, user=self.user)

        issue = ErrorTrackingIssue.objects.create(team=self.team)
        issue_assignment = ErrorTrackingIssueAssignment.objects.create(issue=issue, user_group=user_group)
        assignment_rule = ErrorTrackingAssignmentRule.objects.create(
            team=self.team, user_group=user_group, order_key=0, bytecode={}, filters={}
        )
        grouping_rule = ErrorTrackingGroupingRule.objects.create(
            team=self.team, user_group=user_group, order_key=0, bytecode={}, filters={}
        )

        assert Role.objects.count() == 0

        call_command(
            "migrate_user_groups_to_roles",
            f"--team-id={str(self.team.pk)}",
        )

        # creates role
        assert Role.objects.count() == 1
        role = Role.objects.first()
        assert role is not None
        assert role.name == user_group.name

        # updates member
        assert len(role.members.all()) == 1
        member = role.members.first()
        assert member is not None
        assert member == self.user

        # update error tracking rules
        issue_assignment.refresh_from_db()
        assignment_rule.refresh_from_db()
        grouping_rule.refresh_from_db()

        assert issue_assignment.user_group is None
        assert assignment_rule.user_group is None
        assert grouping_rule.user_group is None

        assert issue_assignment.role == role
        assert assignment_rule.role == role
        assert grouping_rule.role == role

    def test_role_of_same_name_exists(self):
        user_group = UserGroup.objects.create(team=self.team, name="Test group")
        role = Role.objects.create(organization=self.team.organization, name=user_group.name)
        RoleMembership.objects.create(role=role, user=self.user)

        assert Role.objects.count() == 1
        assert RoleMembership.objects.count() == 1

        call_command(
            "migrate_user_groups_to_roles",
            f"--team-id={str(self.team.pk)}",
        )

        assert Role.objects.count() == 1
        assert RoleMembership.objects.count() == 1
