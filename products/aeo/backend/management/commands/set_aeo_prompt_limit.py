from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team import Team

from products.aeo.backend import prompt_limit


class Command(BaseCommand):
    help = "Set how many AI visibility prompts a project can keep turned on at once. Prompts already on stay on."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--max-active-prompts", type=int, required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        if options["max_active_prompts"] < 0:
            raise CommandError("--max-active-prompts can't be negative")
        if not Team.objects.filter(id=options["team_id"]).exists():
            raise CommandError(f"Team {options['team_id']} does not exist")
        limit = prompt_limit.set_max_active_prompts(options["team_id"], options["max_active_prompts"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Team {options['team_id']} can keep {limit.max_active_prompts} prompts on "
                f"({limit.active_prompts} on now)"
            )
        )
