from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team import Team

from products.aeo.backend.models import AEOPrompt
from products.aeo.backend.seeding import import_prompts_csv, upsert_prompts


class Command(BaseCommand):
    help = "Seed the AEO citation prompt set from a CSV — a hand-written control set or an external export."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--csv", type=str, required=True, help="CSV of prompts to import.")
        parser.add_argument(
            "--csv-source",
            choices=[AEOPrompt.Source.IMPORTED, AEOPrompt.Source.MANUAL],
            default=AEOPrompt.Source.IMPORTED,
            help="Source label for CSV rows: 'manual' for the hand-written control set.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Print candidates without saving.")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            team = Team.objects.get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} does not exist")

        candidates = import_prompts_csv(options["csv"], source=options["csv_source"])
        for candidate in candidates:
            self.stdout.write(f"  [{candidate.source}] {candidate.text[:100]}")

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"Dry run: {len(candidates)} candidates, nothing saved"))
            return

        result = upsert_prompts(team, candidates)
        if result["skipped"]:
            self.stdout.write(self.style.WARNING(f"Skipped {result['skipped']} empty or oversized prompt(s)"))
        total_active = AEOPrompt.objects.for_team(team.id).filter(active=True).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {result['created']} new / {result['updated']} updated prompts "
                f"({total_active} active total for team {team.id})"
            )
        )
