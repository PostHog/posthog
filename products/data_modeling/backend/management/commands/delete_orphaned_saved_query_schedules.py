import sys
import asyncio
import logging
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import structlog
from asgiref.sync import sync_to_async

from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_delete_schedule
from posthog.temporal.common.search_attributes import POSTHOG_TEAM_ID_KEY

from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

logger = structlog.get_logger(__name__)


def _get_valid_saved_query_ids(candidate_ids: set[str]) -> set[str]:
    return {
        str(pk)
        for pk in DataWarehouseSavedQuery.objects.filter(id__in=candidate_ids)
        .exclude(deleted=True)
        .values_list("id", flat=True)
    }


class Command(BaseCommand):
    help = "Delete orphaned Temporal schedules for data modeling saved queries"

    def add_arguments(self, parser):
        parser.add_argument(
            "--schedule-ids",
            default=None,
            type=str,
            help="Comma-separated schedule IDs for targeted deletion (skips listing all schedules)",
        )
        parser.add_argument(
            "--team-ids",
            default=None,
            type=str,
            help="Comma-separated team IDs to filter orphans by (uses search attributes if available, falls back to describe)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Preview orphans without deleting",
        )
        parser.add_argument(
            "--concurrency",
            default=20,
            type=int,
            help="Max concurrent Temporal API calls (default: 20)",
        )

    def handle(self, **options):
        logger.setLevel(logging.INFO)
        asyncio.run(self._run(options))

    async def _run(self, options):
        dry_run = options["dry_run"]
        concurrency = options["concurrency"]

        schedule_ids_arg = options.get("schedule_ids")
        team_ids_arg = options.get("team_ids")

        team_ids: set[int] | None = None
        if team_ids_arg:
            try:
                team_ids = {int(tid) for tid in team_ids_arg.split(",")}
            except ValueError:
                raise CommandError("--team-ids must be a comma-separated list of integers")

        temporal = await async_connect()

        # Step 1: Find orphans
        skipped_wrong_team = 0
        if schedule_ids_arg:
            target_ids = {sid.strip() for sid in schedule_ids_arg.split(",") if sid.strip()}
            orphans = await self._find_orphans_from_ids(target_ids)
            # When using --schedule-ids with --team-ids, filter via describe fallback
            if team_ids and orphans:
                orphans, skipped_wrong_team = await self._filter_by_team(temporal, orphans, team_ids, concurrency)
        else:
            # Pass team_ids to use search attribute filtering in the listing query
            orphans = await self._find_orphans_from_listing(temporal, team_ids=team_ids)

        if not orphans:
            logger.info("No orphaned schedules found")
            return

        logger.info(f"Found {len(orphans)} orphaned schedule(s)")

        # Step 3: List orphans
        for schedule_id in sorted(orphans):
            logger.info("Orphaned schedule", schedule_id=schedule_id)

        if dry_run:
            logger.info(f"DRY RUN: Would delete {len(orphans)} schedule(s)")
            return

        # Step 4: Confirm
        if not settings.TEST:
            confirm = input(f"\n\tWill delete {len(orphans)} orphaned schedule(s). Proceed? (y/n) ")
            if confirm.strip().lower() != "y":
                logger.info("Aborting")
                return

        # Step 5: Delete
        deleted, failed = await self._delete_schedules(temporal, orphans, concurrency)

        logger.info(f"Done! Deleted: {deleted}, Failed: {failed}, Skipped (wrong team): {skipped_wrong_team}")

    async def _find_orphans_from_ids(self, target_ids: set[str]) -> set[str]:
        """Check specific schedule IDs against Django — orphan if no valid saved query exists."""
        orphans: set[str] = set()
        valid_uuids: set[str] = set()

        for sid in target_ids:
            try:
                UUID(sid)
                valid_uuids.add(sid)
            except ValueError:
                logger.warning("Invalid UUID, treating as orphan", schedule_id=sid)
                orphans.add(sid)

        if valid_uuids:
            existing = await sync_to_async(_get_valid_saved_query_ids)(valid_uuids)
            for sid in valid_uuids:
                if sid in existing:
                    logger.info("Has valid saved query, skipping", schedule_id=sid)
                else:
                    orphans.add(sid)

        return orphans

    async def _find_orphans_from_listing(self, temporal, team_ids: set[int] | None = None) -> set[str]:
        """List data-modeling-run schedules from Temporal and find orphans.

        If team_ids is provided, uses PostHogTeamId search attribute to pre-filter
        schedules server-side (much faster than listing all + describe each).
        """
        schedule_ids: set[str] = set()
        count = 0

        query = self._build_team_filter_query(team_ids) if team_ids else None
        async for listing in await temporal.list_schedules(query=query):
            if listing.schedule.action.workflow != "data-modeling-run":
                continue
            schedule_ids.add(listing.id)
            count += 1
            if count % 200 == 0:
                sys.stderr.write(".")
                sys.stderr.flush()

        if count >= 200:
            sys.stderr.write("\n")

        logger.info(f"Found {len(schedule_ids)} data-modeling-run schedule(s) in Temporal")

        if not schedule_ids:
            return set()

        # Batch check against Django
        valid_ids = await sync_to_async(_get_valid_saved_query_ids)(schedule_ids)

        return schedule_ids - valid_ids

    @staticmethod
    def _build_team_filter_query(team_ids: set[int]) -> str:
        """Build a Temporal visibility query to filter schedules by PostHogTeamId."""
        if len(team_ids) == 1:
            return f"PostHogTeamId = {next(iter(team_ids))}"
        return f"PostHogTeamId IN ({','.join(str(t) for t in sorted(team_ids))})"

    async def _filter_by_team(
        self, temporal, orphans: set[str], team_ids: set[int], concurrency: int
    ) -> tuple[set[str], int]:
        """Filter orphans by team ID using describe() to extract team_id from payload.

        This is the fallback path used when search attributes are not available
        (e.g. schedules created before search attributes were added).
        """
        import temporalio.converter

        from posthog.temporal.common.codec import EncryptionCodec

        codec = EncryptionCodec(settings=settings)
        payload_converter = temporalio.converter.default().payload_converter
        semaphore = asyncio.Semaphore(concurrency)
        results: dict[str, int | None] = {}

        async def describe_one(schedule_id: str) -> int | None:
            async with semaphore:
                try:
                    handle = temporal.get_schedule_handle(schedule_id)
                    desc = await handle.describe()
                    # Try search attributes first (fast path)
                    team_id_attr = desc.typed_search_attributes.get(POSTHOG_TEAM_ID_KEY)
                    if team_id_attr is not None:
                        return team_id_attr
                    # Fall back to decoding payload (slow path for old schedules)
                    raw_payloads = list(desc.schedule.action.args)
                    if not raw_payloads:
                        return None
                    decoded = await codec.decode(raw_payloads)
                    arg = payload_converter.from_payload(decoded[0])
                    if isinstance(arg, dict):
                        return arg.get("team_id")
                except Exception:
                    logger.warning("Failed to describe schedule", schedule_id=schedule_id)
                return None

        tasks = {sid: asyncio.create_task(describe_one(sid)) for sid in orphans}
        for sid, task in tasks.items():
            results[sid] = await task

        matched: set[str] = set()
        skipped = 0
        for sid, tid in results.items():
            if tid is not None and tid in team_ids:
                matched.add(sid)
            else:
                skipped += 1

        return matched, skipped

    async def _delete_schedules(self, temporal, orphans: set[str], concurrency: int) -> tuple[int, int]:
        """Delete orphaned schedules with bounded concurrency."""
        semaphore = asyncio.Semaphore(concurrency)
        deleted = 0
        failed = 0

        async def delete_one(schedule_id: str) -> bool:
            async with semaphore:
                try:
                    await a_delete_schedule(temporal, schedule_id)
                    logger.info("Deleted schedule", schedule_id=schedule_id)
                    return True
                except Exception:
                    logger.exception("Failed to delete schedule", schedule_id=schedule_id)
                    return False

        tasks = [asyncio.create_task(delete_one(sid)) for sid in orphans]
        for task in asyncio.as_completed(tasks):
            if await task:
                deleted += 1
            else:
                failed += 1

        return deleted, failed
