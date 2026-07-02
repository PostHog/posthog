from django.core.management.base import BaseCommand

import structlog
from asgiref.sync import async_to_sync
from temporalio.client import ScheduleListActionStartWorkflow, ScheduleUpdate, ScheduleUpdateInput
from temporalio.common import SearchAttributePair

from posthog.temporal.common.client import async_connect
from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_TYPE_KEY

from products.data_modeling.backend.schedule import DATA_MODELING_EXECUTE_DAG_WORKFLOW

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Stamp PostHogScheduleType on existing v2 execute-dag schedules so they can be found by a server-side filter"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Only report how many schedules would be stamped, without updating any",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        found, updated, failed = _backfill_schedule_type(dry_run)
        verb = "would stamp" if dry_run else "stamped"
        logger.info("Backfill complete", execute_dag_schedules=found, updated=updated, failed=failed, dry_run=dry_run)
        self.stdout.write(f"execute-dag schedules found: {found}; {verb}: {updated}; failed: {failed}")


async def _updater(input: ScheduleUpdateInput) -> ScheduleUpdate:
    merged = input.description.typed_search_attributes.updated(
        SearchAttributePair(key=POSTHOG_SCHEDULE_TYPE_KEY, value=DATA_MODELING_EXECUTE_DAG_WORKFLOW)
    )
    return ScheduleUpdate(schedule=input.description.schedule, search_attributes=merged)


@async_to_sync
async def _backfill_schedule_type(dry_run: bool) -> tuple[int, int, int]:
    temporal = await async_connect()
    found = 0
    updated = 0
    failed = 0
    async for listing in await temporal.list_schedules():
        action = listing.schedule.action if listing.schedule else None
        if not (
            isinstance(action, ScheduleListActionStartWorkflow)
            and action.workflow == DATA_MODELING_EXECUTE_DAG_WORKFLOW
        ):
            continue
        found += 1
        if dry_run:
            continue
        try:
            await temporal.get_schedule_handle(listing.id).update(_updater)
            updated += 1
        except Exception:
            failed += 1
            logger.exception("Error stamping schedule", schedule_id=listing.id)
    return found, updated, failed
