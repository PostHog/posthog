"""Re-push PostHog secrets to every Vercel resource already linked to a team.

Usage:
    python manage.py backfill_vercel_secrets --dry-run
    python manage.py backfill_vercel_secrets

New installations receive the current secret set when their resource is imported, but
existing ones are only refreshed when a team rotates its API token. Any change to the
secret set therefore needs a one-off sweep to reach installations already out there.

Work is handed to Celery one team at a time, so a single failing installation can't
halt the sweep.
"""

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.tasks.integrations import push_vercel_secrets

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Enqueue a Vercel secret push for every team with a linked Vercel resource."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the teams that would be enqueued, without enqueueing anything.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_ids = sorted(
            Integration.objects.filter(kind=Integration.IntegrationKind.VERCEL)
            .values_list("team_id", flat=True)
            .distinct()
        )

        if options["dry_run"]:
            for team_id in team_ids:
                self.stdout.write(str(team_id))
            self.stdout.write(f"Would enqueue a Vercel secret push for {len(team_ids)} team(s)")
            return

        enqueued = 0
        failed = 0
        for index, team_id in enumerate(team_ids):
            try:
                push_vercel_secrets.apply_async(args=[team_id], countdown=index // 2)
            except Exception as e:
                failed += 1
                logger.exception("Failed to enqueue Vercel secret push", team_id=team_id, integration="vercel")
                capture_exception(e, {"team_id": team_id})
            else:
                enqueued += 1

        self.stdout.write(f"Enqueued a Vercel secret push for {enqueued} team(s), {failed} failed to enqueue")
