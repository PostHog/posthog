from django.core.management.base import BaseCommand

from posthog.models.action.action import Action
from posthog.models.hog_functions.hog_function import HogFunction


def convert_to_hog_function(action: Action) -> HogFunction:
    webhook_url = action.team.slack_incoming_webhook
    message_format = action.slack_message_format

    hog_function = HogFunction(
        filters={"actions": [{"id": action.id}]},
    )

    return hog_function


class Command(BaseCommand):
    help = "Migrate action webhooks to HogFunctions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            type=bool,
            help="If set, will not actually perform the migration, but will print out what would have been done",
        )
        parser.add_argument("--action-ids", type=str, help="Comma separated list of action ids to sync")
        parser.add_argument("--team-ids", type=str, help="Comma separated list of team ids to sync")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        action_ids = options["action_ids"]
        team_ids = options["team_ids"]

        if action_ids and team_ids:
            print("Please provide either action_ids or team_ids, not both")
            return

        query = Action.objects.select_related("team").filter(post_to_slack=True)

        if team_ids:
            print("Migrating all actions for teams:", team_ids)
            query = query.filter(team_id__in=team_ids.split(","))
        elif action_ids:
            print("Migrating actions:", action_ids)
            query = query.filter(id__in=action_ids.split(","))
        else:
            print(f"Migrating all actions")  # noqa T201

        for index, action in enumerate(query.all()):
            print(f"Processing action {action.id}")
            print(convert_to_hog_function(action))

        print("Done")  # noqa T201
