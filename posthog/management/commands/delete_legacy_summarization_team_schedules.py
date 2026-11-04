import asyncio

from django.core.management.base import BaseCommand

from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_delete_schedule

# The retired summarization sweep created one schedule per team under this prefix.
SCHEDULE_ID_PREFIX = "session-summarization-team-"

# Listing a whole namespace can hit its rate limit, so the pages are small and spaced out.
PAGE_SIZE = 200
SECONDS_BETWEEN_PAGES = 1.0
SECONDS_AFTER_RATE_LIMIT = 30.0


async def find_legacy_team_schedule_ids(temporal: Client) -> tuple[list[str], int]:
    """Return the matching schedule IDs and the number of schedules scanned."""
    schedules = await temporal.list_schedules(page_size=PAGE_SIZE)
    matching: list[str] = []
    scanned = 0
    while True:
        try:
            await schedules.fetch_next_page()
        except RPCError as error:
            if error.status != RPCStatusCode.RESOURCE_EXHAUSTED:
                raise
            await asyncio.sleep(SECONDS_AFTER_RATE_LIMIT)
            continue
        page = schedules.current_page or []
        scanned += len(page)
        matching.extend(schedule.id for schedule in page if schedule.id.startswith(SCHEDULE_ID_PREFIX))
        if not schedules.next_page_token:
            return matching, scanned
        await asyncio.sleep(SECONDS_BETWEEN_PAGES)


class Command(BaseCommand):
    help = "One-off: delete the per-team schedules left behind by the retired session summarization sweep"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report the schedules without deleting them")

    def handle(self, *args, **options):
        asyncio.run(self._run(dry_run=options["dry_run"]))

    async def _run(self, dry_run: bool) -> None:
        temporal = await async_connect()
        schedule_ids, scanned = await find_legacy_team_schedule_ids(temporal)
        self.stdout.write(f"Scanned {scanned} schedules and found {len(schedule_ids)} legacy team schedules")
        if dry_run:
            return
        for schedule_id in schedule_ids:
            await a_delete_schedule(temporal, schedule_id)
        self.stdout.write(f"Deleted {len(schedule_ids)} legacy team schedules")
