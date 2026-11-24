from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from redis.exceptions import LockError

from products.aeo.backend.check_brands import enrich_check_brands, enrich_lock, teams_with_checks

# A manual backfill of a large team can outlast the task's lock, so it holds its own for longer.
COMMAND_LOCK_SECONDS = 6 * 60 * 60


class Command(BaseCommand):
    help = (
        "Write the brand rows of checks that have none and of brands whose names changed, and add a catalog "
        "row for every cited domain the catalog lacks. Safe to run again."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, help="Only this team. Every team with checks when left out.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_ids = [options["team_id"]] if options["team_id"] else teams_with_checks()
        for team_id in team_ids:
            lock = enrich_lock(team_id, timeout=COMMAND_LOCK_SECONDS)
            if not lock.acquire(blocking=False):
                self.stdout.write(f"team {team_id}: skipped, a brand pass is already running")
                continue
            try:
                result = enrich_check_brands(team_id)
            finally:
                try:
                    lock.release()
                except LockError:
                    self.stdout.write(f"team {team_id}: the lock expired before the pass ended")
            self.stdout.write(
                f"team {team_id}: {result.brands_added} brands added, {result.stale.brands} brands resolved again, "
                f"{result.unresolved.checks} checks backfilled"
            )
