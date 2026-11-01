import json
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.local_demo import require_local_development
from posthog.models import Team, User

from products.signals.backend.facade.local_demo import seed_local_demo_reports
from products.tasks.backend.facade.local_demo import seed_local_demo_task


class Command(BaseCommand):
    help = "Add repeatable local Inbox and Chat examples to an existing project and user."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--json", action="store_true", help="Print the seeded object IDs as JSON")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id = options["team_id"]
        user_id = options["user_id"]
        try:
            require_local_development()
            task = seed_local_demo_task(team_id=team_id, user_id=user_id)
            reports = seed_local_demo_reports(team_id=team_id, user_id=user_id)
        except (Team.DoesNotExist, User.DoesNotExist, ValueError) as error:
            raise CommandError(str(error)) from error

        result = {
            "team_id": team_id,
            "user_id": user_id,
            "report_ids": reports,
            "task_ids": [task.task_id],
            "run_ids": [task.run_id],
        }
        if options["json"]:
            self.stdout.write(json.dumps(result))
        else:
            self.stdout.write(self.style.SUCCESS(f"Local demo ready for project {team_id}, user {user_id}."))
            self.stdout.write(json.dumps(result, indent=2))
