import dataclasses
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team import Team

from products.aeo.backend import catalog, decisions, topic_tagging
from products.aeo.backend.facade.contracts import PromptLimitError
from products.aeo.backend.models import AEOPrompt
from products.aeo.backend.seeding import PromptCandidate, import_prompts_csv, upsert_prompts


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
        if settings.AEO_JEV_TOPICS:
            candidates = _with_topics(team, candidates)
        for candidate in candidates:
            self.stdout.write(f"  [{candidate.source}] {candidate.text[:100]}")

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"Dry run: {len(candidates)} candidates, nothing saved"))
            return

        try:
            result = upsert_prompts(team, candidates)
        except PromptLimitError as error:
            raise CommandError(str(error)) from error
        if result["skipped"]:
            self.stdout.write(self.style.WARNING(f"Skipped {result['skipped']} empty or oversized prompt(s)"))
        total_active = AEOPrompt.objects.for_team(team.id).filter(active=True).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {result['created']} new / {result['updated']} updated prompts "
                f"({total_active} active total for team {team.id})"
            )
        )


def _with_topics(team: Team, candidates: list[PromptCandidate]) -> list[PromptCandidate]:
    """Give each untagged prompt the closest topic the team already tracks, when Jev is confident of one."""
    untagged = [index for index, candidate in enumerate(candidates) if not candidate.topic]
    existing = list(
        AEOPrompt.objects.for_team(team.id)
        .filter(archived_at__isnull=True)
        .exclude(topic="")
        .values_list("topic", flat=True)
        .distinct()
    )
    if not untagged or not existing:
        return candidates
    own = catalog.own_domains(team.id)
    tagged = decisions.with_fallback(
        lambda: topic_tagging.tag_topics(
            team.id, [candidates[index].text for index in untagged], existing, site=own[0] if own else ""
        ),
        lambda: [""] * len(untagged),
        team_id=team.id,
        feature=topic_tagging.FEATURE,
    )
    result = list(candidates)
    for index, topic in zip(untagged, tagged):
        if topic:
            result[index] = dataclasses.replace(result[index], topic=topic)
    return result
