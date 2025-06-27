from django.core.management.base import BaseCommand
from posthog.models.user_group import UserGroup
from ee.models.rbac.role import Role, RoleMembership
from posthog.models.team import Team
from posthog.models.error_tracking import (
    ErrorTrackingIssueAssignment,
    ErrorTrackingAssignmentRule,
    ErrorTrackingGroupingRule,
)


class Command(BaseCommand):
    help = "Migrate all user groups to be roles instead"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Team ID to migrate")

    def handle(self, *args, **options):
        team_id = options["team_id"]

        if team_id:
            team_ids = [team_id]
        else:
            team_ids = list(UserGroup.objects.values_list("team_id", flat=True).distinct())

        for id in team_ids:
            team = Team.objects.get(id=id)
            user_groups = UserGroup.objects.filter(team=team)

            for user_group in user_groups:
                # create roles for each user group
                (role, _) = Role.objects.get_or_create(organization=team.organization, name=user_group.name)

                # create memberships for each user
                members = user_group.members.all()
                memberships = [RoleMembership(user=user, role=role) for user in members]
                RoleMembership.objects.bulk_create(memberships, ignore_conflicts=True)

                # update references in error tracking models from user_group_id to role_id
                ErrorTrackingIssueAssignment.objects.filter(user_group=user_group).update(role=role, user_group=None)
                ErrorTrackingAssignmentRule.objects.filter(user_group=user_group).update(role=role, user_group=None)
                ErrorTrackingGroupingRule.objects.filter(user_group=user_group).update(role=role, user_group=None)
