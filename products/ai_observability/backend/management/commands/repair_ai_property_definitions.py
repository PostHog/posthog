from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team import Team

from products.ai_observability.backend.property_definition_repair import AIPropertyDefinitionRepair


class Command(BaseCommand):
    help = "Make heavy AI properties available for access rules in one project with recorded AI event definitions."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--team-id", type=int, required=True, help="Team whose project needs AI property definitions."
        )
        parser.add_argument(
            "--apply", action="store_true", help="Create missing definitions. The default is a dry run."
        )

    def handle(self, *args: str, team_id: int, apply: bool = False, **options: object) -> None:
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist as error:
            raise CommandError(f"Team {team_id} does not exist.") from error

        names = AIPropertyDefinitionRepair(team).repair(dry_run=not apply)
        if not names:
            self.stdout.write("No missing definitions, or this project has no recorded AI event definitions.")
            return

        action = "Ensured definitions exist" if apply else "Would create definitions"
        self.stdout.write(f"{action} for project {team.project_id}: {', '.join(names)}")
