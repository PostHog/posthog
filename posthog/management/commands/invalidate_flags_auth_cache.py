"""
Invalidate flags-service auth cache entries for a team.

Clears cached token entries in Redis so the Rust feature-flags service
re-validates against Postgres on the next request. Does NOT revoke the
tokens themselves. Covers team secret tokens, project secret API keys,
and personal API keys that have access to the team.

Usage:
    python manage.py invalidate_flags_auth_cache --team-id 12345
    python manage.py invalidate_flags_auth_cache --team-id 12345 --dry-run
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team.team import Team
from posthog.storage.team_access_cache import token_auth_cache


class Command(BaseCommand):
    help = (
        "Invalidate flags-service auth cache entries for a team. "
        "Clears Redis cache so the Rust service re-fetches from Postgres; does not revoke tokens."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID whose flags auth cache entries to invalidate.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be invalidated without deleting.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        dry_run: bool = options["dry_run"]

        if not dry_run and not token_auth_cache.is_configured:
            raise CommandError("FLAGS_REDIS_URL is not configured. No cache to invalidate.")

        try:
            counts = token_auth_cache.invalidate_team_tokens(team_id, dry_run=dry_run)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} not found.")

        self._print_counts(team_id, counts, dry_run)

    def _print_counts(self, team_id: int, counts: dict[str, int], dry_run: bool) -> None:
        header = (
            f"[DRY RUN] Flags auth cache entries for team {team_id}:"
            if dry_run
            else f"Invalidated flags auth cache entries for team {team_id}:"
        )
        self.stdout.write(header)
        self.stdout.write(f"  Secret tokens:       {counts['secret_tokens']}")
        self.stdout.write(f"  Project secret keys: {counts['project_secret_keys']}")
        self.stdout.write(f"  Personal keys:       {counts['personal_keys']}")

        if dry_run:
            self.stdout.write(f"  Total:               {counts['total']}")
            self.stdout.write(self.style.WARNING("No entries were deleted (dry run)."))
        else:
            self.stdout.write(self.style.SUCCESS(f"  Total invalidated:   {counts['total']}"))
