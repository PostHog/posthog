"""
Management command to find and delete team metadata cache entries whose token no team has.

The flags service trusts a team metadata cache hit without a Postgres check, and the
object-storage copy has no TTL. An entry left behind by a deleted team, or by the old
token of a reset team, keeps resolving until something deletes it.

IMPORTANT: This command requires FLAGS_REDIS_URL to be set, so the delete reaches the
Redis copy that the flags service reads.

Usage:
    # List orphaned entries without changing anything
    python manage.py sweep_orphaned_team_metadata_cache

    # Delete orphaned entries from Redis, object storage, and expiry tracking
    python manage.py sweep_orphaned_team_metadata_cache --delete

    # Delete at most 10 orphaned entries
    python manage.py sweep_orphaned_team_metadata_cache --delete --limit 10
"""

from django.core.management.base import CommandError, CommandParser

from posthog.management.commands._base_hypercache_command import BaseHyperCacheCommand
from posthog.models.utils import mask_key_value
from posthog.storage.hypercache_manager import HyperCacheManagementConfig, sweep_orphaned_token_entries
from posthog.storage.team_metadata_cache import TEAM_HYPERCACHE_MANAGEMENT_CONFIG


class Command(BaseHyperCacheCommand):
    help = "Find team metadata cache entries whose token no team has, and delete them with --delete"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Delete the orphaned entries. Without this flag the command only lists them.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Stop after this many orphaned entries",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of tokens to check against Postgres per query (default: 1000)",
        )

    def get_hypercache_config(self) -> HyperCacheManagementConfig:
        return TEAM_HYPERCACHE_MANAGEMENT_CONFIG

    def handle(self, *args, **options) -> None:
        if not self.check_dedicated_cache_configured():
            return

        delete: bool = options["delete"]
        limit: int | None = options["limit"]
        batch_size: int = options["batch_size"]

        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1")
        if not self.validate_batch_size(batch_size):
            return

        self.print_header("Sweep orphaned team metadata cache entries" + ("" if delete else " (dry run)"))
        result = sweep_orphaned_token_entries(
            self.get_hypercache_config().hypercache,
            delete=delete,
            limit=limit,
            batch_size=batch_size,
        )

        self.stdout.write(f"Tokens checked: {result.tokens_checked}")
        self.stdout.write(f"Orphaned entries: {len(result.orphaned_tokens)}")
        for token in result.orphaned_tokens:
            self.stdout.write(f"  {mask_key_value(token)}")

        if not delete:
            if result.orphaned_tokens:
                self.stdout.write(self.style.WARNING("Dry run: nothing was deleted. Re-run with --delete to delete."))
            return

        self.stdout.write(self.style.SUCCESS(f"Deleted: {len(result.orphaned_tokens) - len(result.failed_tokens)}"))
        if result.failed_tokens:
            masked = ", ".join(mask_key_value(token) for token in result.failed_tokens)
            raise CommandError(f"Failed to delete {len(result.failed_tokens)} entries: {masked}")
