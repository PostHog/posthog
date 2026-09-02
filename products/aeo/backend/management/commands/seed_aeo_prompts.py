from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team import Team

from products.aeo.backend.models import AEOPrompt
from products.aeo.backend.seeding import collect_candidates, upsert_prompts


class Command(BaseCommand):
    help = (
        "Seed the AEO citation prompt set from first-party data "
        "(user-reported signup prompts, AI entry pages, AI-crawled content, GSC queries), "
        "or import a CSV as a control/comparison set."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument(
            "--source",
            choices=["all", "user_reported", "ai_entry_pages", "crawled_content", "gsc"],
            default="all",
            help="Which first-party source(s) to seed from.",
        )
        parser.add_argument("--csv", type=str, help="CSV of prompts to import (control set or external export).")
        parser.add_argument(
            "--csv-source",
            choices=[AEOPrompt.Source.IMPORTED, AEOPrompt.Source.MANUAL],
            default=AEOPrompt.Source.IMPORTED,
            help="Source label for CSV rows: 'manual' for the hand-written control set.",
        )
        parser.add_argument(
            "--expand",
            action="store_true",
            help="Expand AI entry pages and crawled paths into questions via one gateway LLM call.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Print candidates without saving.")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            team = Team.objects.get(id=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} does not exist")

        candidates, notes = collect_candidates(
            team,
            source=options["source"],
            csv_path=options["csv"],
            csv_source=options["csv_source"],
            expand=options["expand"],
        )

        for note in notes:
            self.stdout.write(self.style.WARNING(note))
        for candidate in candidates:
            self.stdout.write(f"  [{candidate.source}] (rank {candidate.rank:g}) {candidate.text[:100]}")

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"Dry run: {len(candidates)} candidates, nothing saved"))
            return

        result = upsert_prompts(team, candidates)
        total_active = AEOPrompt.objects.for_team(team.id).filter(active=True).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {result['created']} new / {result['updated']} updated prompts "
                f"({total_active} active total for team {team.id})"
            )
        )
