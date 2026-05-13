"""`manage.py seed_deployments` — placeholder for realistic dev seeds."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Seed mock deployments for local development. Not yet implemented."

    def handle(self, *args: Any, **options: Any) -> None:
        # TODO(deployments-v1): generate a realistic stream of deployments
        # (varied statuses, authors, branches) for the team passed via
        # --team-id, so the list scene has something to show locally.
        self.stdout.write("TODO: seed_deployments is not implemented yet.")
