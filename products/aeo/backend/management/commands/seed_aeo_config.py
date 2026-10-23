import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team import Team

from products.aeo.backend.facade.api import update_config
from products.aeo.backend.facade.contracts import AEOConfigError


class Command(BaseCommand):
    help = (
        "Load a team's AEO brand config from a JSON file: "
        '{"target_domains": [...], "brand_names": [...], "competitors": [{"name": ..., "domains": [...]}]}.'
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--file", type=str, required=True, help="Path to the JSON config file.")

    def handle(self, *args: Any, **options: Any) -> None:
        team = Team.objects.filter(id=options["team_id"]).only("id", "parent_team_id").first()
        if team is None:
            raise CommandError(f"Team {options['team_id']} does not exist")

        path = Path(options["file"])
        try:
            payload = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise CommandError(f"Could not read {path}: {error}")
        if not isinstance(payload, dict):
            raise CommandError("The config file must hold a JSON object")

        try:
            config = update_config(
                team.id,
                target_domains=payload.get("target_domains", []),
                brand_names=payload.get("brand_names", []),
                competitors=payload.get("competitors", []),
            )
        except AEOConfigError as error:
            raise CommandError(f"Config rejected: {error}") from error

        # The row lives under the parent team, which is the id every reader uses.
        canonical_team_id = team.parent_team_id or team.id
        where = f"team {canonical_team_id}"
        if canonical_team_id != team.id:
            where += f" (parent of environment {team.id})"
        self.stdout.write(
            self.style.SUCCESS(
                f"Stored config for {where}: "
                f"{len(config.target_domains)} target domain(s), {len(config.brand_names)} brand name(s), "
                f"{len(config.competitors)} competitor(s)"
            )
        )
