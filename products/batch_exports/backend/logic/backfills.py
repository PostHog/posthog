"""Backfills of a scheduled batch export: start one, list them, look one up or cancel it.

The facade reaches this module through a call-time import, because it imports the service layer,
the Temporal client and the HogQL parser, none of which may load on the ``django.setup()`` path.
"""

import uuid
import datetime as dt
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db.models import QuerySet

import structlog
import posthoganalytics

from posthog.models import Team
from posthog.temporal.common.client import sync_connect

from products.batch_exports.backend.facade import contracts
from products.batch_exports.backend.hogql_source import (
    DATA_INTERVAL_START_PLACEHOLDER,
    UnsupportedHogQLQueryError,
    find_interval_placeholders,
    parse_hogql_select_for_batch_export,
)
from products.batch_exports.backend.logic.exports import load_batch_export
from products.batch_exports.backend.logic.pagination import select_page
from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportBackfill
from products.batch_exports.backend.service import (
    BatchExportWithNoEndNotAllowedError,
    backfill_export,
    sync_cancel_running_batch_export_backfill,
)

LOGGER = structlog.get_logger(__name__)
_ACTIVE_STATUSES = (BatchExportBackfill.Status.STARTING, BatchExportBackfill.Status.RUNNING)


def validate_date_input(date_input: Any, batch_export: BatchExport) -> dt.datetime:
    """Validate and parse a date/datetime input as a proper dt.datetime.

    If the interval is daily or weekly, we expect the input to be an ISO formatted date string.
    We then need to convert it to a datetime using the batch export's timezone and offset.

    For all other intervals, we expect the input to be an ISO formatted datetime string.

    Args:
        date_input: The datetime input to parse.

    Raises:
        InvalidBackfillRequestError: If the input cannot be parsed.

    Returns:
        The parsed dt.datetime.
    """
    if batch_export.interval == "day" or batch_export.interval == "week":
        try:
            parsed_date = dt.date.fromisoformat(date_input)
        except (TypeError, ValueError):
            # Try to parse as a datetime string so we can give a more helpful error message
            try:
                dt.datetime.fromisoformat(date_input)
            except (TypeError, ValueError):
                raise contracts.InvalidBackfillRequestError(f"Input '{date_input}' is not a valid ISO formatted date.")
            raise contracts.InvalidBackfillRequestError(
                f"Input '{date_input}' is not a valid ISO formatted date. "
                "Daily or weekly batch export backfills expect only the date component, but a time was included."
            )

        if batch_export.interval == "week":
            # Validate that the provided date is on the correct day of the week, according to the batch export's day offset
            # Python's date.isoweekday() returns 1-7 for Monday-Sunday, so we need to convert it to 0-6 for Sunday-Saturday
            normalized_day = parsed_date.isoweekday() % 7
            if normalized_day != batch_export.offset_day:
                # get day of week as string
                day_of_week = parsed_date.strftime("%A")
                expected_day_of_week = batch_export.offset_day_name
                assert expected_day_of_week is not None
                raise contracts.InvalidBackfillRequestError(
                    f"Input {date_input} is not on the correct day of the week for this batch export. "
                    f"{date_input} is a {day_of_week} but this batch export is configured to run "
                    f"weekly on {expected_day_of_week}."
                )

        # If we have an offset hour, add it to the parsed datetime
        # Also, apply the timezone to the parsed datetime
        time_of_day = dt.time.min if batch_export.offset_hour is None else dt.time(hour=batch_export.offset_hour)
        parsed = dt.datetime.combine(parsed_date, time_of_day).replace(tzinfo=batch_export.timezone_info)

    else:
        try:
            parsed = dt.datetime.fromisoformat(date_input)
        except (TypeError, ValueError):
            raise contracts.InvalidBackfillRequestError(f"Input {date_input} is not a valid ISO formatted datetime.")

        if parsed.tzinfo is None:
            raise contracts.InvalidBackfillRequestError(f"Input {date_input} is naive.")

    return parsed


def _get_progress(backfill: BatchExportBackfill) -> contracts.BatchExportBackfillProgress | None:
    """Return progress information containing total runs, finished runs, and progress percentage.

    To reduce the number of database calls we make (which could be expensive when fetching a list of backfills) we
    only get the list of completed runs from the DB if the backfill is still running.
    """
    if backfill.status == BatchExportBackfill.Status.COMPLETED:
        return contracts.BatchExportBackfillProgress(
            total_runs=backfill.total_expected_runs, finished_runs=backfill.total_expected_runs, progress=1.0
        )
    elif backfill.status not in _ACTIVE_STATUSES:
        # if backfill finished in some other state then progress info may not be meaningful
        return None

    total_runs = backfill.total_expected_runs
    if not total_runs:
        return None

    if backfill.start_at is None and backfill.adjusted_start_at is None:
        # if it's just a single run, backfilling from the beginning of time, we can't calculate progress based on
        # the number of completed runs so better to return None
        return None

    finished_runs = backfill.get_finished_runs()
    # just make sure we never return a progress > 1
    total_runs = max(total_runs, finished_runs)
    return contracts.BatchExportBackfillProgress(
        total_runs=total_runs, finished_runs=finished_runs, progress=round(finished_runs / total_runs, ndigits=1)
    )


def _to_backfill_detail(backfill: BatchExportBackfill) -> contracts.BatchExportBackfillDetail:
    return contracts.BatchExportBackfillDetail(
        id=backfill.id,
        team_id=backfill.team_id,
        batch_export_id=backfill.batch_export_id,
        start_at=backfill.start_at,
        end_at=backfill.end_at,
        status=backfill.status,
        created_at=backfill.created_at,
        finished_at=backfill.finished_at,
        last_updated_at=backfill.last_updated_at,
        total_records_count=backfill.total_records_count,
        adjusted_start_at=backfill.adjusted_start_at,
        progress=_get_progress(backfill),
    )


def _query_export_backfills(team_id: int, export_id: UUID) -> QuerySet[BatchExportBackfill]:
    # The progress of a backfill reads the interval of its batch export.
    return BatchExportBackfill.objects.filter(batch_export_id=export_id, batch_export__team_id=team_id).select_related(
        "batch_export"
    )


def _get_backfill(team_id: int, export_id: UUID, backfill_id: UUID) -> BatchExportBackfill:
    try:
        return _query_export_backfills(team_id, export_id).get(id=backfill_id)
    except BatchExportBackfill.DoesNotExist as e:
        raise contracts.BatchExportBackfillNotFoundError() from e


def list_backfills(
    team_id: int, export_id: UUID, page: contracts.ListPage
) -> list[contracts.BatchExportBackfillDetail]:
    backfills = select_page(
        _query_export_backfills(team_id, export_id),
        page,
        ordering_fields=contracts.BATCH_EXPORT_BACKFILL_ORDERING_FIELDS,
    )
    return [_to_backfill_detail(backfill) for backfill in backfills]


def get_backfill(team_id: int, export_id: UUID, backfill_id: UUID) -> contracts.BatchExportBackfillDetail:
    return _to_backfill_detail(_get_backfill(team_id, export_id, backfill_id))


def _check_earliest_backfill_allowed(team_id: int, batch_export: BatchExport) -> None:
    """Check that a backfill from the beginning of time can run for this team and batch export."""
    # Currently, backfills from the beginning of time usually fail due to us hitting ClickHouse memory limits.
    # Therefore, this feature is behind a feature flag while we improve backfilling behavior.
    team = Team.objects.select_related("organization").get(id=team_id)
    if not posthoganalytics.feature_enabled(
        "batch-export-earliest-backfill",
        str(team.uuid),
        groups={"organization": str(team.organization.id)},
        group_properties={
            "organization": {
                "id": str(team.organization.id),
                "created_at": team.organization.created_at,
            }
        },
        send_feature_flag_events=False,
    ):
        raise contracts.InvalidBackfillRequestError(
            "Backfilling from the beginning of time is not enabled for this team."
        )

    if batch_export.model == BatchExport.Model.HOGQL and (hogql_query := batch_export.hogql_query) is not None:
        try:
            parsed = parse_hogql_select_for_batch_export(hogql_query)
        except UnsupportedHogQLQueryError as e:
            raise contracts.InvalidBackfillRequestError(str(e)) from e
        if DATA_INTERVAL_START_PLACEHOLDER in find_interval_placeholders(parsed):
            # TODO: We should maybe support beginning-of-time backfills with this placeholder.
            raise contracts.InvalidBackfillRequestError(
                "This query references {data_interval_start}, which is unavailable when backfilling from the "
                "beginning of time. Provide 'start_at' or remove {data_interval_start} from the query."
            )


def create_backfill(
    team_id: int, export_id: UUID, start_at_input: Any, end_at_input: Any
) -> contracts.BatchExportBackfillStart:
    """Start a backfill of a batch export.

    Args:
        team_id: The team creating the backfill
        export_id: The batch export to backfill
        start_at_input: ISO formatted datetime string for backfill start
        end_at_input: ISO formatted datetime string for backfill end
    """
    batch_export = load_batch_export(team_id, export_id, "destination")

    if start_at_input is None:
        _check_earliest_backfill_allowed(team_id, batch_export)

    concurrency_limit = settings.BATCH_EXPORT_MAX_CONCURRENT_BACKFILLS_PER_TEAM
    active_backfills = BatchExportBackfill.objects.filter(team_id=team_id, status__in=_ACTIVE_STATUSES).count()
    if active_backfills >= concurrency_limit:
        raise contracts.TooManyConcurrentBackfillsError(
            f"This team already has {concurrency_limit} batch export backfills running. "
            f"Wait for some to finish or cancel them before creating more."
        )

    temporal = sync_connect()

    if start_at_input is not None:
        start_at = validate_date_input(start_at_input, batch_export)
    else:
        start_at = None

    if end_at_input is not None:
        end_at = validate_date_input(end_at_input, batch_export)
    else:
        end_at = None

    # Note: earliest backfill date validation and adjustment is now done in the Temporal workflow
    # via the get_backfill_info activity. This allows the potentially slow ClickHouse query to run
    # asynchronously rather than blocking the HTTP request.

    backfill_id = str(uuid.uuid4())
    started = contracts.BatchExportBackfillStart(
        backfill_id=backfill_id, destination_type=batch_export.destination.type
    )

    if start_at is None or end_at is None:
        backfill_export(
            temporal=temporal,
            batch_export_id=str(batch_export.pk),
            team_id=team_id,
            start_at=start_at,
            end_at=end_at,
            backfill_id=backfill_id,
        )
        return started

    if start_at >= end_at:
        raise contracts.InvalidBackfillRequestError("The initial backfill datetime 'start_at' must be before 'end_at'")
    if end_at > dt.datetime.now(dt.UTC):
        raise contracts.InvalidBackfillRequestError(f"The provided 'end_at' ({end_at.isoformat()}) is in the future")

    try:
        backfill_export(
            temporal=temporal,
            batch_export_id=str(batch_export.pk),
            team_id=team_id,
            start_at=start_at,
            end_at=end_at,
            backfill_id=backfill_id,
        )
        return started
    except BatchExportWithNoEndNotAllowedError:
        raise contracts.InvalidBackfillRequestError("Backfilling a BatchExport with no end date is not allowed")


def cancel_backfill(team_id: int, export_id: UUID, backfill_id: UUID) -> None:
    backfill = _get_backfill(team_id, export_id, backfill_id)
    if backfill.status not in _ACTIVE_STATUSES:
        raise contracts.InvalidBackfillRequestError(f"Cannot cancel a backfill that is in '{backfill.status}' status")

    temporal = sync_connect()
    try:
        sync_cancel_running_batch_export_backfill(temporal, backfill)
    except Exception as e:
        # It could be the case that the backfill is already cancelled but our database hasn't been updated yet.
        # In this case, we can just ignore the error but log it for visibility (in case there is an actual
        # issue).
        LOGGER.warning("Error cancelling batch export backfill: %s", e)
