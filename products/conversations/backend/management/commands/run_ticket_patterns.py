"""Run ticket spike detection for one team, without Temporal.

Calls the same activity body the coordinator schedules, so what it prints is what a real tick
would report.
"""

from __future__ import annotations

import asyncio

from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team

from products.conversations.backend.temporal.ticket_patterns.coordinator import _read_settings
from products.conversations.backend.temporal.ticket_patterns.detect import _detect
from products.conversations.backend.temporal.ticket_patterns.schemas import EligibleTeam


class Command(BaseCommand):
    help = "Detect ticket spikes for a single team and print what was found."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the spikes without capturing events or marking tickets as reported.",
        )

    def handle(self, *args, **options) -> None:
        team = Team.objects.filter(id=options["team_id"]).select_related("organization").first()
        if team is None:
            raise CommandError(f"Team {options['team_id']} not found")
        if not team.organization.is_ai_data_processing_approved:
            raise CommandError("The organization has not approved AI data processing")
        if not (team.conversations_settings or {}).get("ticket_patterns_enabled"):
            raise CommandError("Ticket spike detection is off for this team")

        eligible = EligibleTeam(team_id=team.id, settings=_read_settings(team.conversations_settings or {}))
        result = asyncio.run(_detect(eligible, report=not options["dry_run"], check_flag=False))

        self.stdout.write(f"Scanned {result.candidate_count} tickets (the rollout flag is not checked here)")
        for cluster in result.clusters:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{cluster.topic}: {len(cluster.ticket_ids)} tickets from "
                    f"{cluster.requester_count} customers\n  {cluster.summary}"
                )
            )
        if not result.clusters:
            self.stdout.write("No spikes found")
