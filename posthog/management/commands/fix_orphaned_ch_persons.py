import sys
import logging
import argparse
from collections.abc import Callable

from django.core.management.base import BaseCommand

import structlog

from posthog.kafka_client.routing import flush_all_producers
from posthog.models.person.bulk_delete import queue_event_deletion_by_uuid, queue_recording_deletion_by_distinct_id
from posthog.models.person.deletion import (
    OrphanDataErasure,
    OrphanRepairResult,
    count_live_ch_persons,
    find_orphaned_ch_persons,
    orphan_share_refusal,
    plan_orphan_data_erasure,
    tombstone_orphaned_ch_persons,
)

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)

_FLUSH_TIMEOUT_SECONDS = 5 * 60


class Command(BaseCommand):
    help = (
        "Tombstone ClickHouse person rows that are live in ClickHouse but absent from the persons DB. "
        "Dry-run by default."
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
        parser.add_argument(
            "--force",
            action="store_true",
            help="Apply even when the orphans are more than 5%% of the team's live ClickHouse persons.",
        )
        parser.add_argument(
            "--delete-events",
            action="store_true",
            help="Erasure only: also queue deletion of the repaired persons' events. Needs --person-uuid.",
        )
        parser.add_argument(
            "--delete-recordings",
            action="store_true",
            help="Erasure only: also delete the repaired persons' recordings. Needs --person-uuid and --reason. "
            "A rerun finds the recordings only until the weekly deletion sweep removes the persons' ClickHouse "
            "mappings; after that it exits with the persons it can no longer check.",
        )
        parser.add_argument("--reason", default="", help="Why the recordings are deleted. Stored on the workflow.")

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

    delete_events = options.get("delete_events", False)
    delete_recordings = options.get("delete_recordings", False)
    erasing = delete_events or delete_recordings
    reason = options.get("reason", "")
    # Deleted data cannot come back, so an erasure names its persons and never overrides the restore guard.
    if erasing and (all_persons or options.get("force")):
        logger.error("--delete-events and --delete-recordings need --person-uuid and refuse --all and --force")
        exit(1)
    if delete_recordings and not reason:
        logger.error("--delete-recordings needs --reason")
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

    refusal = orphan_share_refusal(team_id, len(orphans), count_live_ch_persons(team_id)) if orphans else None
    if refusal:
        if not dry_run and not options.get("force"):
            logger.error(refusal)
            exit(1)
        logger.warning(refusal)

    result = tombstone_orphaned_ch_persons(team_id, orphans, dry_run=dry_run)
    _log_result(team_id, result)

    if dry_run:
        if erasing:
            preview = plan_orphan_data_erasure(
                team_id, uuids, pending_uuids=[o.uuid for o in orphans], with_recordings=delete_recordings
            )
            _log_erasure(team_id, preview)
            _report_erasure_gaps(team_id, preview, delete_recordings=delete_recordings, log=logger.warning)
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

    if not erasing:
        return
    erasure = plan_orphan_data_erasure(team_id, uuids, with_recordings=delete_recordings)
    _log_erasure(team_id, erasure)
    # Queued first because it is one idempotent insert, so a failure to start a recording workflow still leaves the
    # events queued.
    if delete_events:
        queue_event_deletion_by_uuid(team_id, erasure.person_uuids, actor=None)
    if delete_recordings:
        workflow_ids = queue_recording_deletion_by_distinct_id(
            team_id, erasure.recording_distinct_ids, deleted_by="fix_orphaned_ch_persons", reason=reason
        )
        if workflow_ids:
            logger.info(
                "Recording deletion started and has not finished. Check these workflows for the result.",
                team_id=team_id,
                workflow_ids=workflow_ids,
            )
    if _report_erasure_gaps(team_id, erasure, delete_recordings=delete_recordings, log=logger.error):
        exit(1)


def _report_erasure_gaps(
    team_id: int, erasure: OrphanDataErasure, *, delete_recordings: bool, log: Callable[..., object]
) -> bool:
    recordings_may_remain = delete_recordings and bool(
        erasure.unconfirmed_distinct_ids or erasure.excluded_distinct_ids or erasure.persons_without_distinct_ids
    )
    if not recordings_may_remain and not erasure.not_erasable_uuids:
        return False
    log(
        "This erasure is incomplete. A person in not_erasable_uuids has no persons-DB tombstone, so this run erased "
        "nothing of theirs: the person is live, or the cleanup already removed its tombstone. Check each one with "
        "person_inspect. Recordings may remain under the distinct ids printed above and for a person in "
        "persons_without_distinct_ids. Check each one, then delete its recordings from the team admin.",
        team_id=team_id,
        not_erasable_uuids=erasure.not_erasable_uuids,
        persons_without_distinct_ids=erasure.persons_without_distinct_ids,
    )
    return True


def _print_for_operator(label: str, values: list[str]) -> None:
    # Written to the operator's terminal and not logged, because a distinct id can be an email address and this
    # command runs to erase that data.
    if values:
        sys.stdout.write(f"{label}:\n" + "\n".join(values) + "\n")


def _log_erasure(team_id: int, erasure: OrphanDataErasure) -> None:
    logger.info(
        "Orphan data erasure",
        team_id=team_id,
        persons=len(erasure.person_uuids),
        recording_distinct_ids=len(erasure.recording_distinct_ids),
        excluded_distinct_ids=len(erasure.excluded_distinct_ids),
        unconfirmed_distinct_ids=len(erasure.unconfirmed_distinct_ids),
        persons_without_distinct_ids=erasure.persons_without_distinct_ids,
        not_erasable_uuids=erasure.not_erasable_uuids,
    )
    _print_for_operator("Unconfirmed distinct ids", erasure.unconfirmed_distinct_ids)
    _print_for_operator("Excluded distinct ids", erasure.excluded_distinct_ids)


def _log_result(team_id: int, result: OrphanRepairResult) -> None:
    verb = "Would tombstone" if result.dry_run else "Tombstoned"
    logger.info(
        f"{verb} orphaned ClickHouse persons",
        team_id=team_id,
        dry_run=result.dry_run,
        orphaned_persons=len(result.orphaned_person_uuids),
        tombstoned_persons=result.tombstoned_persons,
        republished_persons=result.republished_persons,
        skipped_live_persons=result.skipped_live_persons,
        reverse_drift_mappings=len(result.reverse_drift_mappings),
    )
    if result.reverse_drift_mappings:
        logger.warning(
            "Found distinct_ids tombstoned in ClickHouse whose person is still live in the persons DB "
            "(reverse drift). Repair these with person_divergence repair, not this command.",
            team_id=team_id,
        )
        _print_for_operator(
            "Reverse drift mappings",
            [f"{distinct_id} {person}" for distinct_id, person in result.reverse_drift_mappings],
        )
