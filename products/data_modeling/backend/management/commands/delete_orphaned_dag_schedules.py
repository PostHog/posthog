import sys
import asyncio
import logging
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import structlog
from asgiref.sync import sync_to_async
from temporalio.client import ScheduleListActionStartWorkflow

from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_delete_schedule

from products.data_modeling.backend.logic.cohort_scheduling import dag_id_from_schedule_id
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.schedule import DATA_MODELING_EXECUTE_DAG_WORKFLOW

logger = structlog.get_logger(__name__)


def _live_dag_ids(candidate_ids: set[str]) -> set[str]:
    return {str(pk) for pk in DAG.objects.filter(id__in=candidate_ids).values_list("id", flat=True)}


class Command(BaseCommand):
    help = "Delete execute-dag Temporal schedules whose DAG no longer exists"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-ids",
            default=None,
            type=str,
            help="Comma-separated team IDs to filter by, via the PostHogTeamId search attribute",
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
        team_ids: set[int] | None = None
        if options["team_ids"]:
            try:
                team_ids = {int(tid) for tid in options["team_ids"].split(",")}
            except ValueError:
                raise CommandError("--team-ids must be a comma-separated list of integers")

        temporal = await async_connect()
        orphans = await self._find_orphans(temporal, team_ids)

        if not orphans:
            logger.info("No orphaned execute-dag schedules found")
            return

        logger.info(f"Found {len(orphans)} orphaned execute-dag schedule(s)")
        for schedule_id in sorted(orphans):
            logger.info("Orphaned schedule", schedule_id=schedule_id)

        if options["dry_run"]:
            logger.info(f"DRY RUN: Would delete {len(orphans)} schedule(s)")
            return

        if not settings.TEST:
            confirm = input(f"\n\tWill delete {len(orphans)} orphaned schedule(s). Proceed? (y/n) ")
            if confirm.strip().lower() != "y":
                logger.info("Aborting")
                return

        deleted, failed = await self._delete_schedules(temporal, orphans, options["concurrency"])
        logger.info(f"Done! Deleted: {deleted}, Failed: {failed}")

    async def _find_orphans(self, temporal, team_ids: set[int] | None) -> set[str]:
        """A DAG deleted without its schedules leaves no row to reconcile from, so the sweep
        has to start from Temporal and resolve back into Postgres.
        """
        dag_id_by_schedule: dict[str, str] = {}
        unparseable: set[str] = set()
        count = 0

        query = self._build_team_filter_query(team_ids) if team_ids else None
        async for listing in await temporal.list_schedules(query=query):
            action = listing.schedule.action
            if not isinstance(action, ScheduleListActionStartWorkflow):
                continue
            if action.workflow != DATA_MODELING_EXECUTE_DAG_WORKFLOW:
                continue
            dag_id = dag_id_from_schedule_id(listing.id)
            try:
                UUID(dag_id)
            except ValueError:
                # Never delete on a guess: an id we can't resolve to a DAG gets reported, not swept.
                unparseable.add(listing.id)
                continue
            dag_id_by_schedule[listing.id] = dag_id
            count += 1
            if count % 200 == 0:
                sys.stderr.write(".")
                sys.stderr.flush()

        if count >= 200:
            sys.stderr.write("\n")

        for schedule_id in sorted(unparseable):
            logger.warning("Schedule id does not carry a DAG UUID, skipping", schedule_id=schedule_id)

        logger.info(f"Found {len(dag_id_by_schedule)} execute-dag schedule(s) in Temporal")
        if not dag_id_by_schedule:
            return set()

        live = await sync_to_async(_live_dag_ids)(set(dag_id_by_schedule.values()))
        return {schedule_id for schedule_id, dag_id in dag_id_by_schedule.items() if dag_id not in live}

    @staticmethod
    def _build_team_filter_query(team_ids: set[int]) -> str:
        if len(team_ids) == 1:
            return f"PostHogTeamId = {next(iter(team_ids))}"
        return f"PostHogTeamId IN ({','.join(str(t) for t in sorted(team_ids))})"

    async def _delete_schedules(self, temporal, orphans: set[str], concurrency: int) -> tuple[int, int]:
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
