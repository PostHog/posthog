from posthog.management.commands.migrate_action_webhooks import migrate_all_teams_action_webhooks
from posthog.models import Action, Team
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.test.base import BaseTest


advanced_message_format = """Event: [event] [event.event] [event.link] [event.uuid]
Person: [person] [person.link] [person.properties.foo.bar]
Groups: [groups.organization]  [groups.organization.properties.foo.bar]
Action: [action.name] [action.link]"""


class TestMigrateActionWebhooks(BaseTest):
    action: Action

    def setUp(self):
        super().setUp()
        self.team.slack_incoming_webhook = "https://webhooks.slack.com/123"
        self.team.save()
        self.action = Action.objects.create(
            created_by=self.user,
            name="Test Action",
            team_id=self.team.id,
            slack_message_format="[event] triggered by [person]",
            post_to_slack=True,
            steps_json=[
                {
                    "event": None,  # All events
                }
            ],
        )

    def test_migrate_large_number_of_actions_across_teams(self):
        organization = self.organization
        number_of_teams = 3
        number_of_actions_per_team = 150

        # Create 3 teams
        teams = [
            Team.objects.create(
                name=f"Team {i}", slack_incoming_webhook="https://slack.com/webhook", organization=organization
            )
            for i in range(number_of_teams)
        ]

        # Create 150 actions for each team (450 total)
        actions = []
        for team in teams:
            for i in range(number_of_actions_per_team):
                actions.append(
                    Action.objects.create(
                        team=team,
                        name=f"Action {i} for team {team.id}",
                        post_to_slack=True,
                        deleted=False,
                        steps_json=[{"event": None}],
                    )
                )

        # Run the migration
        migrate_all_teams_action_webhooks()

        # Count resulting HogFunctions
        hog_function_count = HogFunction.objects.filter(team_id__in=[team.id for team in teams]).count()
        self.assertEqual(
            hog_function_count,
            number_of_teams * number_of_actions_per_team,
            f"Expected {number_of_teams * number_of_actions_per_team} HogFunctions, but got {hog_function_count}",
        )

        # Verify all actions for test teams have been properly migrated (meaning post_to_slack is False and deleted is False)
        actions_to_migrate = Action.objects.filter(
            team_id__in=[team.id for team in teams], post_to_slack=True, deleted=False
        )
        self.assertEqual(
            actions_to_migrate.count(),
            0,
            f"Expected 0 actions left to migrate, but found {actions_to_migrate.count()}. "
            + f"Actions still needing migration: {list(actions_to_migrate.values_list('id', 'team_id'))}",
        )
