"""Fast-path wrapper around `posthog.demo.products.hedgebox.wa_activation_demo.seed_wa_activation_demo`.

The full `generate_demo_data` command also seeds the web-analytics activation
demo (as part of the Hedgebox matrix), but takes ~1-2 min for the event
simulation. This wrapper runs only the activation portion against an existing
team, which is much faster during iteration on the catalog product.

Usage:
    python manage.py seed_wa_activation_demo --team-id 1
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.demo.products.hedgebox.matrix import HedgeboxMatrix
from posthog.demo.products.hedgebox.wa_activation_demo import seed_wa_activation_demo
from posthog.models.team.team import Team

from products.data_warehouse.backend.models.credential import get_or_create_datawarehouse_credential


class Command(BaseCommand):
    help = (
        "Seed the web analytics activation demo (web_analytics_activation_base_events table + "
        "'Web analytics activation funnel' insight) for a team."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Target team id")

    def handle(self, *args, **options) -> None:
        team_id: int = options["team_id"]
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} does not exist")

        if settings.TEST or not settings.OBJECT_STORAGE_ENABLED:
            raise CommandError(
                "OBJECT_STORAGE must be enabled to seed the WA activation demo (it writes CSVs to MinIO)."
            )

        access_key = settings.OBJECT_STORAGE_ACCESS_KEY_ID
        access_secret = settings.OBJECT_STORAGE_SECRET_ACCESS_KEY
        if not access_key or not access_secret or not settings.OBJECT_STORAGE_ENDPOINT:
            raise CommandError("OBJECT_STORAGE_ACCESS_KEY_ID / SECRET / ENDPOINT not set.")

        user = team.organization.members.first()
        if user is None:
            raise CommandError(f"Team {team_id} has no organization members — cannot attribute `created_by`.")

        credential = get_or_create_datawarehouse_credential(
            team_id=team.pk,
            access_key=access_key,
            access_secret=access_secret,
        )

        # We don't run the full event simulation; the matrix is just a holder for
        # `now` and the warehouse-CSV upsert helper that seed_wa_activation_demo reuses.
        matrix = HedgeboxMatrix(
            seed=secrets.token_hex(8),
            now=datetime.now(tz=UTC),
            days_past=1,
            days_future=1,
            n_clusters=0,
        )

        self.stdout.write(f"Seeding WA activation demo for team={team_id} ({team.name!r})")
        seed_wa_activation_demo(matrix, team, user, credential)
        self.stdout.write(self.style.SUCCESS("Done."))
