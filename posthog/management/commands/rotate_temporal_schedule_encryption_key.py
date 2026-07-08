import csv
import sys
import typing
import asyncio
import datetime as dt
import collections.abc
from argparse import ArgumentParser

from django.conf import settings
from django.core.management.base import BaseCommand

import structlog
from cryptography.fernet import InvalidToken
from rich.console import Console
from rich.table import Table
from temporalio.client import (
    ScheduleActionStartWorkflow,
    ScheduleListActionStartWorkflow,
    ScheduleUpdate,
    ScheduleUpdateInput,
)

from posthog.temporal.common import client, codec

LOGGER = structlog.get_logger(__name__)

ScheduleID = str


class FailedSchedule(typing.TypedDict):
    id: ScheduleID
    error: str


class SkippedSchedule(typing.TypedDict):
    id: ScheduleID
    reason: str


class Results(typing.NamedTuple):
    """Results of a command execution."""

    failed: list[FailedSchedule]
    success: list[ScheduleID]
    skipped: list[SkippedSchedule]


def print_results(results: Results) -> None:
    """Print results to stdout as a rich table."""
    table = Table(title="Schedule encryption key rotation")

    table.add_column("Schedule ID")
    table.add_column("Status")
    table.add_column("Details")

    for schedule_id in results.success:
        table.add_row(schedule_id, "Success", "")

    for skipped in results.skipped:
        table.add_row(
            skipped["id"],
            "Skipped",
            skipped["reason"],
        )

    for failed in results.failed:
        table.add_row(
            failed["id"],
            "Failed",
            failed["error"],
        )

    console = Console()
    with console.pager(styles=True):
        console.print(table)


def write_csv_results(results: Results) -> None:
    """Write results to stdout as a CSV."""
    writer = csv.writer(sys.stdout)

    writer.writerow(["schedule_id", "status", "details"])

    for schedule_id in results.success:
        writer.writerow([schedule_id, "success", ""])

    for skipped in results.skipped:
        writer.writerow(
            [
                skipped["id"],
                "skipped",
                skipped["reason"],
            ]
        )

    for failed in results.failed:
        writer.writerow(
            [
                failed["id"],
                "failed",
                failed["error"],
            ]
        )


class Command(BaseCommand):
    help = "Rotate the encryption key used in one or more Temporal schedules."

    def create_parser(self, prog_name: str, subcommand: str, **kwargs: typing.Any):
        parser = super().create_parser(prog_name, subcommand, **kwargs)
        parser.description = """
Rotate the encryption key used in one or more Temporal schedules.

The command can rotate the encryption key for all schedules, for specific schedules
specified by their ID, or for schedules filtered by the workflow they invoke.

In order to rotate an encryption key, the Django settings must configure a
'TEMPORAL_SECRET_KEY' and one or more 'TEMPORAL_FALLBACK_SECRET_KEYS'. The encryption
key will be rotated from any of the fallback keys to the `TEMPORAL_SECRET_KEY`.

Temporal doesn't actually have a 'rotate' operation, so what this command does is read
a schedule's inputs, implicitly decrypting them with a fallback key, and updates the
schedule with the same inputs, which implicitly encrypts them with
`TEMPORAL_SECRET_KEY`.
"""

        parser.epilog = """
Examples:

  manage.py rotate_temporal_schedule_encryption_key id one-schedule-id another-schedule-id
  manage.py rotate_temporal_schedule_encryption_key workflow bigquery-export snowflake-export
  manage.py rotate_temporal_schedule_encryption_key all
"""
        return parser

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--format", choices=("table", "csv"), default="table", help="Output format")
        parser.add_argument("--dry-run", action="store_true", help="Do a dry-run, nothing will be updated")

        subparsers = parser.add_subparsers(dest="subcommand", required=True)

        by_ids = subparsers.add_parser("id")
        by_ids.add_argument("ids", nargs="+", help="One or more schedule IDs whose encryption key to rotate")

        by_workflows = subparsers.add_parser("workflow")
        by_workflows.add_argument(
            "workflows",
            nargs="+",
            help="Rotate the encryption key of all schedules matching one or more workflow types",
        )

        _ = subparsers.add_parser("all")

    def handle(self, **options: typing.Any) -> None:
        dry_run = options["dry_run"]

        LOGGER.info("Starting", dry_run=dry_run)

        match options["subcommand"]:
            case "all":
                results = asyncio.run(self.run_all(dry_run=dry_run))
            case "id":
                results = asyncio.run(self.run_by_ids(options["ids"], dry_run=dry_run))
            case "workflow":
                results = asyncio.run(self.run_by_workflow(options["workflows"], dry_run=dry_run))
            case invalid:
                raise ValueError(f"Invalid subcommand '{invalid}'")

        match options["format"]:
            case "table":
                print_results(results)
            case "csv":
                write_csv_results(results)
            case invalid:
                raise ValueError(f"Invalid format '{invalid}'")

    async def run_all(self, /, dry_run: bool) -> Results:
        """Rotate encryption key for all schedules."""
        temporal = await client.async_connect()

        async def iter_ids() -> collections.abc.AsyncIterator[ScheduleID]:
            async for list_schedule in await temporal.list_schedules():
                yield list_schedule.id

        results = await self.run_by_ids(iter_ids(), dry_run=dry_run)

        return results

    async def run_by_workflow(self, workflows_iter: collections.abc.Iterable[str], /, dry_run: bool) -> Results:
        """Rotate encryption key for schedules that trigger specific workflows."""
        temporal = await client.async_connect()
        workflows = set(workflows_iter)

        async def iter_ids() -> collections.abc.AsyncIterator[ScheduleID]:
            async for list_schedule in await temporal.list_schedules():
                action = list_schedule.schedule.action if list_schedule.schedule else None
                if isinstance(action, ScheduleListActionStartWorkflow) and action.workflow in workflows:
                    yield list_schedule.id

        results = await self.run_by_ids(iter_ids(), dry_run=dry_run)

        return results

    async def run_by_ids(
        self, ids: collections.abc.Iterable[ScheduleID] | collections.abc.AsyncIterable[ScheduleID], /, dry_run: bool
    ) -> Results:
        """Rotate encryption key for schedules with given IDs.

        In order to rotate an encryption key for a schedule we first read its current
        arguments. This implicitly decrypts the arguments, which means that we must
        still support the old encryption key as a fallback. Then, we update the
        schedule with the same arguments, which encrypts them with the main key,
        completing the rotation.
        """
        temporal = await client.async_connect()
        failed: list[FailedSchedule] = []
        success: list[ScheduleID] = []
        skipped: list[SkippedSchedule] = []

        async def do_update(input: ScheduleUpdateInput) -> ScheduleUpdate:
            action = input.description.schedule.action
            assert isinstance(action, ScheduleActionStartWorkflow)

            decoded_args = await temporal.data_converter.decode(list(action.args))
            action.args = decoded_args

            now = dt.datetime.now(dt.UTC)
            re_encryption_message = f"Schedule inputs re-encrypted on {now.isoformat()}"

            current_message = input.description.schedule.state.note
            if current_message is None:
                input.description.schedule.state.note = re_encryption_message
            else:
                input.description.schedule.state.note = re_encryption_message + ". " + current_message

            return ScheduleUpdate(schedule=input.description.schedule)

        async for schedule_id in _as_async_iter(ids):
            handle = temporal.get_schedule_handle(schedule_id)

            try:
                description = await handle.describe()
            except Exception:
                LOGGER.warning("Schedule not found", schedule_id=schedule_id, dry_run=dry_run)

                failed_schedule: FailedSchedule = {"id": schedule_id, "error": "Schedule was not found"}
                failed.append(failed_schedule)

                continue

            action = description.schedule.action
            assert isinstance(action, ScheduleActionStartWorkflow)

            is_not_encrypted = any(
                payload.metadata.get("encoding") != b"binary/encrypted" for payload in list(action.args)
            )
            if is_not_encrypted:
                LOGGER.info(
                    "Skipping schedule that is NOT encrypted",
                    schedule_id=schedule_id,
                    dry_run=dry_run,
                )
                skipped_schedule: SkippedSchedule = {
                    "id": schedule_id,
                    "reason": "No encryption in use",
                }
                skipped.append(skipped_schedule)
                continue

            uses_main_key = await _payloads_use_main_key(list(action.args))

            if uses_main_key:
                LOGGER.info(
                    "Skipping schedule already encrypted with main key",
                    schedule_id=schedule_id,
                    dry_run=dry_run,
                )
                skipped_schedule = {
                    "id": schedule_id,
                    "reason": "Main encryption key already in use",
                }
                skipped.append(skipped_schedule)
                continue

            if dry_run:
                LOGGER.info("Encryption key not rotated in a dry-run", dry_run=dry_run, schedule_id=schedule_id)
                skipped_schedule = {"id": schedule_id, "reason": "Dry-run"}
                skipped.append(skipped_schedule)
                continue

            LOGGER.info("Rotating encryption key for schedule", dry_run=dry_run, schedule_id=schedule_id)
            try:
                await handle.update(do_update)
            except Exception:
                LOGGER.exception("Update failed", schedule_id=schedule_id, dry_run=dry_run)

                failed_schedule = {"id": schedule_id, "error": "Update operation failed"}
                failed.append(failed_schedule)

                continue

            success.append(schedule_id)

        return Results(failed=failed, success=success, skipped=skipped)


async def _as_async_iter(
    it: collections.abc.Iterable[ScheduleID] | collections.abc.AsyncIterable[ScheduleID],
) -> collections.abc.AsyncIterator[ScheduleID]:
    if hasattr(it, "__aiter__"):
        async for item in it:
            yield item
    else:
        for item in it:
            yield item


async def _payloads_use_main_key(payloads) -> bool:
    if not payloads:
        return True
    main_key_codec = codec.EncryptionCodec(codec._prepare_key(codec._load_as_bytes(settings.TEMPORAL_SECRET_KEY)), [])
    try:
        await main_key_codec.decode(payloads)
    except InvalidToken:
        return False
    return True
