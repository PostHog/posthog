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

from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

logger = structlog.get_logger(__name__)


def _get_valid_saved_query_ids(candidate_ids: set[str]) -> set[str]:
    return {
        str(pk)
        for pk in DataWarehouseSavedQuery.objects.filter(id__in=candidate_ids, deleted=False).values_list(
            "id", flat=True
        )
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
            help="Comma-separated team IDs to filter orphans by (requires describe per orphan)",
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
        if schedule_ids_arg:
            target_ids = {sid.strip() for sid in schedule_ids_arg.split(",") if sid.strip()}
            orphans = await self._find_orphans_from_ids(target_ids)
        else:
            orphans = await self._find_orphans_from_listing(temporal)

        if not orphans:
            logger.info("No orphaned schedules found")
            return

        logger.info(f"Found {len(orphans)} orphaned schedule(s)")

        # Step 2: Filter by team if requested
        skipped_wrong_team = 0
        if team_ids:
            orphans, skipped_wrong_team = await self._filter_by_team(temporal, orphans, team_ids, concurrency)
            if not orphans:
                logger.info("No orphans match the specified team IDs")
                return
            logger.info(f"After team filter: {len(orphans)} orphan(s), {skipped_wrong_team} skipped")

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

    async def _find_orphans_from_listing(self, temporal) -> set[str]:
        """List all data-modeling-run schedules from Temporal and find orphans."""
        schedule_ids: set[str] = set()
        count = 0

        async for listing in await temporal.list_schedules():
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

    async def _filter_by_team(
        self, temporal, orphans: set[str], team_ids: set[int], concurrency: int
    ) -> tuple[set[str], int]:
        """Filter orphans by team ID using describe() to extract team_id from payload."""
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
