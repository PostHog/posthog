from posthog.models.user_group import UserGroup, UserGroupMembership
from ee.models.rbac.role import Role
from django.core.management import call_command
from posthog.test.base import BaseTest
from posthog.models.error_tracking import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingAssignmentRule,
)


class TestAddQuestionIdsToSurveys(BaseTest):
    def test_migrates_group_and_members_to_roles(self):
        user_group = UserGroup.objects.create(team=self.team, name="Test group")
        UserGroupMembership.objects.create(group=user_group, user=self.user)

        issue = ErrorTrackingIssue.objects.create(team=self.team)
        ErrorTrackingIssueAssignment.objects.create(issue=issue, user_group=user_group)
        ErrorTrackingAssignmentRule.objects.create(
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
        assert role.name == user_group.name

        # updates member
        assert len(role.members.all()) == 1
        member = role.members.first()
        assert member == self.user

        # updates member
        assert len(role.members.all()) == 1
        member = role.members.first()
        assert member == self.user
