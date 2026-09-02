import logging
import argparse

from django.core.management.base import BaseCommand

import structlog

from posthog.kafka_client.routing import flush_all_producers
from posthog.models.person.deletion import OrphanRepairResult, find_orphaned_ch_persons, tombstone_orphaned_ch_persons

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)

_FLUSH_TIMEOUT_SECONDS = 5 * 60


class Command(BaseCommand):
    help = (
        "Tombstone ClickHouse person rows that are live in ClickHouse but absent from the persons DB "
        "(the inverse of fix_person_distinct_ids_after_delete). Dry-run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Team to repair (required).")
        parser.add_argument(
            "--person-uuid",
            action="append",
            default=None,
            dest="person_uuid",
            help="Scope the repair to this person UUID. Repeat for several; omit with --all.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Scan every live ClickHouse person for the team (full scan). Mutually exclusive with --person-uuid.",
        )
        parser.add_argument(
            "--dry-run",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Report what would change without writing (default: on). Pass --no-dry-run to apply.",
        )

    def handle(self, *args, **options):
        run(options)


def run(options) -> None:
    team_id = options.get("team_id")
    if not team_id:
        logger.error("You must specify --team-id to run this script")
        exit(1)

    uuids = options.get("person_uuid")
    all_persons = options.get("all", False)
    if (not uuids and not all_persons) or (uuids and all_persons):
        logger.error("You must specify exactly one of --person-uuid or --all to run this script")
        exit(1)

    dry_run = options["dry_run"]

    orphans = find_orphaned_ch_persons(team_id, uuids)
    if uuids:
        found = {o.uuid for o in orphans}
        not_orphaned = [u for u in uuids if u not in found]
        if not_orphaned:
            # Requested but not orphaned: either live in the persons DB (safe to leave)
            # or absent from ClickHouse entirely. Never tombstoned by this command.
            logger.warning(
                "Some requested UUIDs are not orphaned (live in persons DB or absent from ClickHouse); skipping them",
                team_id=team_id,
                not_orphaned=not_orphaned,
            )

    result = tombstone_orphaned_ch_persons(team_id, orphans, dry_run=dry_run)
    _log_result(team_id, result)

    if dry_run:
        logger.info("Dry run: no tombstones were produced. Re-run with --no-dry-run to apply.")
        return

    logger.info("Waiting on Kafka producer flush, for up to 5 minutes")
    undelivered = flush_all_producers(_FLUSH_TIMEOUT_SECONDS)
    if undelivered:
        logger.error(
            "Kafka flush left messages undelivered — tombstones may not have landed in ClickHouse",
            team_id=team_id,
            undelivered=undelivered,
        )
        exit(1)
    logger.info("Kafka producer queue flushed.")


def _log_result(team_id: int, result: OrphanRepairResult) -> None:
    verb = "Would tombstone" if result.dry_run else "Tombstoned"
    logger.info(
        f"{verb} orphaned ClickHouse persons",
        team_id=team_id,
        dry_run=result.dry_run,
        orphaned_persons=len(result.orphaned_person_uuids),
        tombstoned_persons=result.tombstoned_persons,
        tombstoned_mappings=result.tombstoned_mappings,
        skipped_reassigned_mappings=result.skipped_reassigned_mappings,
        reverse_drift_mappings=len(result.reverse_drift_mappings),
    )
    if result.reverse_drift_mappings:
        logger.warning(
            "Found distinct_ids tombstoned in ClickHouse whose person is still live in the persons DB "
            "(reverse drift). Repair these with fix_person_distinct_ids_after_delete, not this command.",
            team_id=team_id,
            reverse_drift=result.reverse_drift_mappings,
        )
