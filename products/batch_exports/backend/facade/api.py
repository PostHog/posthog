"""
Facade for batch_exports.

Capability-oriented functions that take and return the framework-free contracts in
``facade/contracts.py``. The facade never hands an ORM instance across the boundary, and
every read is scoped by ``team_id``. Mappers are explicit, so the shape a consumer sees
is visible in one place.

``service.py`` imports ``temporalio`` at module scope, and the startup import budget
(``posthog/test/repo_invariants/test_startup_import_budget.py``) forbids both that module
and ``temporalio`` on the ``django.setup()`` path. Core config-time consumers import this
facade, so it reaches the service only through ``_service()``, which imports it at call
time. For the same reason the Temporal client is built in ``_get_temporal_client()``, and
the HogQL, destination config, file download, run and backfill modules load through
``_import_hogql_source()``, ``_import_destination_config()``, ``_import_file_downloads()``,
``_import_runs()`` and ``_import_backfills()``.

Temporal workflow and activity registration crosses as objects, not data, so it lives in
``facade/temporal.py``. The destination clients the warehouse writers reuse live in
``facade/destinations/``, and the stream transformers in ``facade/pipeline.py``. None of
those may be imported from here.
"""

import datetime as dt
from collections.abc import Mapping, Sequence
from types import ModuleType
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce

import structlog

from posthog.models import Team, User
from posthog.models.integration import Integration

from products.batch_exports.backend import (
    destination_tests,
    filters as batch_export_filters,
)
from products.batch_exports.backend.billing import exclude_non_billable_runs
from products.batch_exports.backend.models.batch_export import (
    BATCH_EXPORT_INTERVALS,
    BatchExport,
    BatchExportBackfill,
    BatchExportDestination,
    BatchExportRun,
    get_batch_exports_using_integration,
)

from . import contracts

if TYPE_CHECKING:
    from temporalio.client import Client

__all__ = [
    "FAILED_BACKFILL_STATUSES",
    "MultipleBatchExportsError",
    "backfill_batch_export",
    "cancel_batch_export_backfill",
    "cancel_batch_export_run",
    "cancel_file_download",
    "coerce_destination_config",
    "count_batch_exports_for_teams",
    "count_hogql_rows",
    "create_batch_export",
    "create_batch_export_backfill",
    "create_workflows_backfill_export",
    "delete_batch_export",
    "delete_batch_exports_for_teams",
    "describe_destination_test",
    "drop_unknown_hogql_modifiers",
    "find_hogql_interval_placeholders",
    "get_batch_export_backfill",
    "get_batch_export_by_name",
    "get_batch_export_run",
    "get_file_download_run",
    "get_file_download_url",
    "get_latest_completed_run",
    "get_latest_run",
    "get_run_failure",
    "get_teams_with_active_batch_exports",
    "get_teams_with_billable_rows_exported",
    "list_backfills_for_export",
    "list_batch_export_backfills",
    "list_batch_export_runs",
    "list_batch_exports_using_integration",
    "list_file_download_runs",
    "list_latest_failed_runs",
    "list_supported_intervals",
    "retry_batch_export_run",
    "run_destination_test_step",
    "start_file_download",
    "validate_batch_export_filters",
    "validate_destination_config",
    "validate_hogql_query",
]

logger = structlog.get_logger(__name__)

# The statuses that make the latest run of an export an actionable failure.
FAILED_RUN_STATUSES = (
    BatchExportRun.Status.FAILED,
    BatchExportRun.Status.FAILED_RETRYABLE,
    BatchExportRun.Status.TIMEDOUT,
    BatchExportRun.Status.TERMINATED,
)

# The statuses of a backfill that can stop before it exports anything.
FAILED_BACKFILL_STATUSES = frozenset(
    {
        BatchExportBackfill.Status.CANCELLED,
        BatchExportBackfill.Status.FAILED,
        BatchExportBackfill.Status.FAILED_RETRYABLE,
        BatchExportBackfill.Status.TERMINATED,
        BatchExportBackfill.Status.TIMEDOUT,
    }
)

# An on-demand export has no name of its own, so a failure list labels it generically.
ON_DEMAND_EXPORT_NAME = "On-demand batch export"


class MultipleBatchExportsError(Exception):
    """Raised when a lookup that expects at most one batch export matches several."""


def _service() -> ModuleType:
    """Import the service layer at call time. See the module docstring for why."""
    from products.batch_exports.backend import service

    return service


def _import_hogql_source() -> ModuleType:
    """Import the HogQL helpers at call time. See the module docstring for why."""
    from products.batch_exports.backend import hogql_source

    return hogql_source


def _import_destination_config() -> ModuleType:
    """Import the destination config checks at call time. See the module docstring for why."""
    from products.batch_exports.backend.logic import (  # noqa: PLC0415 — keeps the service layer and temporalio off the django.setup() path
        destination_config,
    )

    return destination_config


def _import_file_downloads() -> ModuleType:
    """Import the file download module at call time. See the module docstring for why."""
    from products.batch_exports.backend.logic import file_downloads

    return file_downloads


def _import_runs() -> ModuleType:
    """Import the run module at call time. See the module docstring for why."""
    from products.batch_exports.backend.logic import runs

    return runs


def _import_backfills() -> ModuleType:
    """Import the backfill module at call time. See the module docstring for why."""
    from products.batch_exports.backend.logic import backfills

    return backfills


def _get_temporal_client() -> "Client":
    """Connect to Temporal at call time. See the module docstring for why."""
    from posthog.temporal.common.client import sync_connect

    return sync_connect()


def _to_ref(batch_export: BatchExport) -> contracts.BatchExportRef:
    return contracts.BatchExportRef(id=batch_export.id, name=batch_export.name)


def _to_detail(batch_export: BatchExport) -> contracts.BatchExportDetail:
    # The destination config is an encrypted field, so reading it decrypts the destination's
    # credentials. Only the two event filters are lifted out of it, which is all any consumer reads.
    # Do not widen this to the whole config unless we are certain all credentials have been migrated
    # to integrations and dropped from the config.
    config = batch_export.destination.config
    return contracts.BatchExportDetail(
        id=batch_export.id,
        team_id=batch_export.team_id,
        name=batch_export.name,
        interval=batch_export.interval,
        paused=batch_export.paused,
        created_at=batch_export.created_at,
        last_updated_at=batch_export.last_updated_at,
        destination_type=batch_export.destination.type,
        # A stored filter can be null, not only absent, so the fallback covers both.
        exclude_events=tuple(config.get("exclude_events") or ()),
        include_events=tuple(config.get("include_events") or ()),
    )


def _to_destination_test_step(
    step: destination_tests.base.DestinationTestStep,
) -> contracts.DestinationTestStep:
    result = None
    if step.result is not None:
        result = contracts.DestinationTestStepResult(status=str(step.result.status), message=step.result.message)
    return contracts.DestinationTestStep(name=step.name, description=step.description, result=result)


def _to_backfill_summary(backfill: BatchExportBackfill) -> contracts.BatchExportBackfillSummary:
    return contracts.BatchExportBackfillSummary(
        id=backfill.id,
        status=backfill.status,
        start_at=backfill.start_at,
        adjusted_start_at=backfill.adjusted_start_at,
        created_at=backfill.created_at,
        last_updated_at=backfill.last_updated_at,
    )


def _to_run_summary(run: BatchExportRun) -> contracts.BatchExportRunSummary:
    return contracts.BatchExportRunSummary(
        id=run.id,
        status=run.status,
        latest_error=run.latest_error,
        data_interval_start=run.data_interval_start,
        data_interval_end=run.data_interval_end,
        finished_at=run.finished_at,
        created_at=run.created_at,
        last_updated_at=run.last_updated_at,
    )


def list_batch_exports_using_integration(team_id: int, integration_id: int) -> list[contracts.BatchExportRef]:
    """Return the live batch exports that write through this integration."""
    return [_to_ref(batch_export) for batch_export in get_batch_exports_using_integration(team_id, integration_id)]


def count_batch_exports_for_teams(team_ids: Sequence[int]) -> int:
    """Count the batch exports these teams have, not counting deleted ones."""
    return BatchExport.objects.filter(team_id__in=team_ids, deleted=False).count()


def list_latest_failed_runs(team_id: int) -> list[contracts.FailedBatchExportRun]:
    """Return the exports whose most recent run failed.

    Only the latest run of each export counts, so an export that has recovered does not
    appear. A paused export is left out too: its last failure is no longer actionable.
    """
    latest_run_ids = (
        BatchExportRun.objects.filter(
            batch_export__team_id=team_id,
            batch_export__deleted=False,
            batch_export__paused=False,
        )
        .order_by("batch_export_id", "-created_at")
        .distinct("batch_export_id")
        .values_list("id", flat=True)
    )

    # nosemgrep: idor-lookup-without-team (IDs from team-scoped queryset)
    failed_runs = BatchExportRun.objects.filter(id__in=latest_run_ids, status__in=FAILED_RUN_STATUSES).select_related(
        "batch_export"
    )

    return [
        contracts.FailedBatchExportRun(
            export_id=run.parent.id,
            export_name=getattr(run.parent, "name", ON_DEMAND_EXPORT_NAME),
            error=run.latest_error,
            failed_at=run.finished_at,
        )
        for run in failed_runs
    ]


def get_run_failure(run_id: UUID | str, team_id: int) -> contracts.BatchExportRunFailure | None:
    """Return a failed run with the export and team that own it, or None for an on-demand run.

    An on-demand export has no page of its own, so there is nothing to point a person at.
    The team is matched against either parent, so an on-demand run still resolves and
    returns None rather than raising.
    """
    run = BatchExportRun.objects.select_related("batch_export", "batch_export_on_demand").get(
        Q(batch_export__team_id=team_id) | Q(batch_export_on_demand__team_id=team_id),
        id=run_id,
    )
    export = run.parent

    if not isinstance(export, BatchExport):
        return None

    return contracts.BatchExportRunFailure(
        run_id=run.id,
        team_id=export.team_id,
        export_id=export.id,
        export_name=export.name,
        last_updated_at=run.last_updated_at,
    )


def get_teams_with_billable_rows_exported(begin: dt.datetime, end: dt.datetime) -> list[contracts.TeamTotal]:
    """Sum the rows each team exported through billable runs that finished in the period."""
    completed_runs = BatchExportRun.objects.filter(
        finished_at__gte=begin,
        finished_at__lte=end,
        status=BatchExportRun.Status.COMPLETED,
    )
    rows = (
        exclude_non_billable_runs(completed_runs)
        .values(team_id=Coalesce(F("batch_export__team_id"), F("batch_export_on_demand__team_id")))
        # A run that recorded no count leaves records_completed null, so a team whose runs are
        # all null would sum to null. Coalesce keeps every total an integer.
        .annotate(total=Coalesce(Sum("records_completed"), 0))
    )
    return [contracts.TeamTotal(team_id=row["team_id"], total=row["total"]) for row in rows]


def get_teams_with_active_batch_exports() -> list[contracts.TeamTotal]:
    """Count the batch exports each team currently runs on a schedule.

    Deleted exports are excluded, which the usage report query this replaces does not do.
    Deletion never leaves an export paused - `service.delete_batch_export` saves a stale
    instance over the paused flag - so that query counts every export a team has ever
    deleted, and the number only ever grows. It drops once the usage report moves here.
    """
    rows = BatchExport.objects.filter(paused=False, deleted=False).values("team_id").annotate(total=Count("id"))
    return [contracts.TeamTotal(team_id=row["team_id"], total=row["total"]) for row in rows]


def delete_batch_exports_for_teams(team_ids: Sequence[int]) -> None:
    """Delete the batch exports of deleted teams, and the Temporal schedules behind them.

    A CASCADE delete of the team would leave the schedules running, so each export is
    deleted with its destination and its schedule together.
    """
    service = _service()
    temporal = _get_temporal_client()

    for batch_export in BatchExport.objects.filter(team_id__in=team_ids, deleted=False):
        schedule_id = batch_export.id

        batch_export.delete()
        batch_export.destination.delete()

        try:
            service.batch_export_delete_schedule(temporal, str(schedule_id))
        except service.BatchExportServiceScheduleNotFound as e:
            logger.warning("Schedule not found during team deletion", schedule_id=e.schedule_id)


def get_batch_export_by_name(team_id: int, name: str, destination_type: str) -> contracts.BatchExportDetail | None:
    """Return the one live export with this name and destination, or None."""
    try:
        batch_export = BatchExport.objects.select_related("destination").get(
            team_id=team_id, name=name, destination__type=destination_type, deleted=False
        )
    except BatchExport.DoesNotExist:
        return None
    except BatchExport.MultipleObjectsReturned as e:
        raise MultipleBatchExportsError(
            f"Team {team_id} has more than one batch export named {name!r} to {destination_type!r}"
        ) from e

    return _to_detail(batch_export)


def list_backfills_for_export(export_id: UUID, team_id: int) -> list[contracts.BatchExportBackfillSummary]:
    """Return every backfill of an export, newest first. An export can have any number of them."""
    backfills = BatchExportBackfill.objects.filter(batch_export_id=export_id, team_id=team_id).order_by("-created_at")
    return [_to_backfill_summary(backfill) for backfill in backfills]


def get_latest_run(export_id: UUID, team_id: int) -> contracts.BatchExportRunSummary | None:
    """Return the most recently created run of an export, or None if it has never run."""
    run = (
        BatchExportRun.objects.filter(batch_export_id=export_id, batch_export__team_id=team_id)
        .order_by("-created_at")
        .first()
    )
    return _to_run_summary(run) if run is not None else None


def get_latest_completed_run(export_id: UUID, team_id: int) -> contracts.BatchExportRunSummary | None:
    """Return the run that finished most recently, of those that completed."""
    run = (
        BatchExportRun.objects.filter(
            batch_export_id=export_id,
            batch_export__team_id=team_id,
            status=BatchExportRun.Status.COMPLETED,
        )
        .order_by("-finished_at")
        .first()
    )
    return _to_run_summary(run) if run is not None else None


def _schedule_and_save(batch_export: BatchExport) -> None:
    """Create the Temporal schedule of a new export, then save the export and its destination."""
    service = _service()

    # Schedule first, then the rows, which is the order every caller uses today. It trades one
    # failure for the other: a failed save leaves an orphaned schedule, where the reverse order
    # would leave a row pointing at no schedule. Neither is compensated yet.
    service.sync_batch_export(batch_export, created=True)

    with transaction.atomic():
        batch_export.destination.save()
        batch_export.save()


def create_batch_export(
    team_id: int,
    *,
    name: str,
    destination_type: str,
    destination_config: Mapping[str, object],
    interval: str,
    paused: bool = False,
    end_at: dt.datetime | None = None,
) -> contracts.BatchExportDetail:
    """Create a batch export, its destination, and the Temporal schedule that drives it."""
    batch_export = BatchExport(
        team_id=team_id,
        destination=BatchExportDestination(type=destination_type, config=dict(destination_config)),
        name=name,
        interval=interval,
        paused=paused,
        end_at=end_at,
    )
    _schedule_and_save(batch_export)
    return _to_detail(batch_export)


def validate_batch_export_filters(filters: object) -> None:
    """Check the event filters a batch export stores.

    Raises ``contracts.InvalidBatchExportFilters`` unless ``filters`` is None or a list of
    supported filters.
    """
    batch_export_filters.validate_batch_export_filters(filters)


def create_workflows_backfill_export(
    team_id: int,
    *,
    hog_function_id: UUID,
    name: str,
    event_filters: list[dict[str, object]] | None,
    last_modified_by_id: int,
) -> contracts.BatchExportRef:
    """Create the paused, hourly export that backfills events into a hog function.

    Raises ``contracts.InvalidBatchExportFilters`` when ``event_filters`` fail the checks the
    batch export API applies.
    """
    validate_batch_export_filters(event_filters)

    batch_export = BatchExport(
        team_id=team_id,
        destination=BatchExportDestination(
            type=BatchExportDestination.Destination.WORKFLOWS,
            config={"hog_function_id": str(hog_function_id)},
        ),
        name=name,
        model=BatchExport.Model.EVENTS,
        interval="hour",
        paused=True,
        filters=event_filters,
        last_modified_by_id=last_modified_by_id,
    )
    _schedule_and_save(batch_export)
    return _to_ref(batch_export)


def delete_batch_export(export_id: UUID, team_id: int) -> None:
    """Delete a batch export: pause it, cancel its work, then drop its Temporal schedule."""
    service = _service()
    batch_export = BatchExport.objects.select_related("destination").get(id=export_id, team_id=team_id)
    service.delete_batch_export(batch_export)


def backfill_batch_export(
    export_id: UUID, team_id: int, start_at: dt.datetime | None, end_at: dt.datetime | None
) -> str:
    """Start a backfill of an export over a date range, and return the backfill id.

    With no ``end_at`` the backfill runs until it catches up with realtime, then unpauses
    the export.
    """
    service = _service()
    return service.backfill_export(_get_temporal_client(), str(export_id), team_id, start_at, end_at)


def list_supported_intervals() -> tuple[str, ...]:
    """Return the intervals a batch export may be scheduled on."""
    return tuple(interval for interval, _ in BATCH_EXPORT_INTERVALS)


def validate_destination_config(destination_type: str, config: Mapping[str, Any], *, partial: bool) -> dict[str, Any]:
    """Check a destination config against the workflow inputs of its destination type.

    With ``partial``, a required field may be missing, as in a patch. Returns a copy of the
    config with values converted to the declared types. Raises
    ``contracts.InvalidDestinationConfigError`` when a field is unknown, missing or of the
    wrong type.
    """
    return _import_destination_config().validate_destination_config(destination_type, config, partial=partial)


def coerce_destination_config(destination_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """Return a stored destination config with its values restored to their declared types.

    The stored config reads back with stringified scalars, so ``"False"`` becomes ``False``.
    """
    return _service().coerce_config_to_declared_types(destination_type, config)


def describe_destination_test(destination_type: str) -> contracts.DestinationTest:
    """Return the steps of a destination's connection test, with no step run."""
    destination_test = destination_tests.get_destination_test(destination=destination_type)
    return contracts.DestinationTest(steps=tuple(_to_destination_test_step(step) for step in destination_test.steps))


def run_destination_test_step(
    team_id: int,
    *,
    destination_type: str,
    config: Mapping[str, object],
    integration_id: int | None,
    step: int,
) -> contracts.DestinationTestStep:
    """Run one step of a destination's connection test, and return that step with its result.

    ``config`` is a destination config that already passed validation. The step reaches the
    destination over the network. When the destination authenticates through an integration,
    the integration's config and secrets override any key of the same name in ``config``.
    """
    destination_test = destination_tests.get_destination_test(destination=destination_type)

    test_configuration = dict(config)
    if integration_id is not None:
        integration = Integration.objects.get(id=integration_id, team_id=team_id)
        test_configuration = {
            **test_configuration,
            **integration.config,
            **integration.sensitive_config,
            "integration": integration,
        }

    destination_test.configure(**test_configuration)
    return _to_destination_test_step(destination_test.run_step(step))


def drop_unknown_hogql_modifiers(stored: Mapping[str, Any]) -> dict[str, Any]:
    """Return stored HogQL modifiers without keys that the HogQL schema no longer defines."""
    from products.batch_exports.backend.hogql_source import (  # noqa: PLC0415 — keeps the HogQL parser and printer off the django.setup() path
        drop_unknown_hogql_modifiers as drop_unknown,
    )

    return drop_unknown(dict(stored))


def find_hogql_interval_placeholders(hogql_query: str) -> frozenset[str]:
    """Return the interval placeholders a batch export HogQL query references.

    The names are ``data_interval_start`` and ``data_interval_end``. Raises
    ``contracts.UnsupportedHogQLQueryError`` when the query is not a SELECT, or references
    another placeholder.
    """
    hogql_source = _import_hogql_source()
    return frozenset(
        hogql_source.find_interval_placeholders(hogql_source.parse_hogql_select_for_batch_export(hogql_query))
    )


def validate_hogql_query(
    team_id: int, *, user_id: int, hogql_query: str, hogql_modifiers: Mapping[str, object] | None
) -> None:
    """Check that a HogQL query can power a batch export, with the user's table and property permissions.

    Raises ``contracts.UnsupportedHogQLQueryError`` when it cannot.
    """
    hogql_source = _import_hogql_source()
    hogql_source.validate_hogql_query_for_batch_export(
        hogql_query,
        Team.objects.get(id=team_id),
        user=User.objects.get(id=user_id),
        modifiers=hogql_source.load_hogql_modifiers(dict(hogql_modifiers) if hogql_modifiers is not None else None),
    )


def count_hogql_rows(
    team_id: int,
    *,
    user_id: int,
    hogql_query: str,
    hogql_modifiers: Mapping[str, object] | None,
    data_interval_start: dt.datetime | None,
    data_interval_end: dt.datetime | None,
) -> int:
    """Count the rows a HogQL batch export would produce if it ran now, over the given bounds.

    The query runs in ClickHouse with a short timeout. Raises
    ``contracts.UnsupportedHogQLQueryError`` when the query cannot power a batch export, and
    lets the HogQL and ClickHouse query errors through: ``ExposedHogQLError``,
    ``ExposedCHQueryError`` and ``ClickHouseQueryTimeOut``.
    """
    return _import_file_downloads().count_rows_for_hogql_batch_export(
        team_id,
        hogql_query,
        user_id=user_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        hogql_modifiers=dict(hogql_modifiers) if hogql_modifiers is not None else None,
    )


def list_file_download_runs(
    team_id: int, *, offset: int, limit: int
) -> tuple[list[contracts.BatchExportRunSummary], int]:
    """Return one page of the team's file download runs, newest first, and how many there are in total."""
    runs, count = _import_file_downloads().list_file_download_runs(team_id, offset=offset, limit=limit)
    return [_to_run_summary(run) for run in runs], count


def get_file_download_run(team_id: int, run_id: UUID) -> contracts.FileDownloadRun:
    """Return a file download run. Raises ``contracts.FileDownloadNotFoundError`` when the team has no such run."""
    return _import_file_downloads().get_file_download_run(team_id, run_id)


def start_file_download(team_id: int, *, user_id: int, request: contracts.FileDownloadRequest) -> UUID:
    """Create a file download run and start the workflow that writes its files. Return the run id.

    A team can have only ``BATCH_EXPORT_MAX_CONCURRENT_ON_DEMAND_PER_TEAM`` file downloads
    starting or running. Over that limit, this raises
    ``contracts.TooManyConcurrentFileDownloadsError`` and creates nothing. When the workflow
    does not start, the run is saved as failed and this raises ``contracts.FileDownloadStartError``.
    """
    return _import_file_downloads().start_file_download(team_id, user_id, request)


def cancel_file_download(team_id: int, run_id: UUID) -> str:
    """Cancel a file download that is starting or running, and return the status of the run after that.

    Raises ``contracts.InvalidFileDownloadRequestError`` when the run is in another status.
    """
    return _import_file_downloads().cancel_file_download(team_id, run_id)


def get_file_download_url(team_id: int, run_id: UUID, part: str | None) -> str:
    """Return a short-lived URL that downloads one file of a completed file download run.

    ``part`` is a file id, or a file index in download order. Without it, the first file is
    returned. Raises ``contracts.InvalidFileDownloadRequestError`` when the run did not
    complete, the part is not valid or the file has expired, and
    ``contracts.FileDownloadNotFoundError`` when the run or the file does not exist.
    """
    return _import_file_downloads().get_file_download_url(team_id, run_id, part)


def list_batch_export_runs(
    team_id: int, export_id: UUID, *, filters: contracts.BatchExportRunFilters, page: contracts.ListPage
) -> list[contracts.BatchExportRunDetail]:
    """Return one page of an export's runs that match ``filters``, ordered by ``created_at`` or ``data_interval_start``."""
    return _import_runs().list_runs(team_id, export_id, filters, page)


def get_batch_export_run(
    team_id: int, export_id: UUID, run_id: UUID, *, filters: contracts.BatchExportRunFilters
) -> contracts.BatchExportRunDetail:
    """Raises ``contracts.BatchExportRunNotFoundError`` unless the team has this run and it matches ``filters``."""
    return _import_runs().get_run(team_id, export_id, run_id, filters)


def retry_batch_export_run(
    team_id: int, export_id: UUID, run_id: UUID, *, filters: contracts.BatchExportRunFilters
) -> str:
    """Backfill a run's data interval again and return the backfill id. Raises as ``get_batch_export_run`` does."""
    return _import_runs().retry_run(team_id, export_id, run_id, filters)


def cancel_batch_export_run(
    team_id: int, export_id: UUID, run_id: UUID, *, filters: contracts.BatchExportRunFilters
) -> None:
    """Cancel a starting or running run. Raises ``contracts.InvalidBatchExportRunRequestError`` in any other status."""
    _import_runs().cancel_run(team_id, export_id, run_id, filters)


def list_batch_export_backfills(
    team_id: int, export_id: UUID, *, page: contracts.ListPage
) -> list[contracts.BatchExportBackfillDetail]:
    """Return one page of an export's backfills, ordered by ``created_at`` or ``start_at``."""
    return _import_backfills().list_backfills(team_id, export_id, page)


def get_batch_export_backfill(team_id: int, export_id: UUID, backfill_id: UUID) -> contracts.BatchExportBackfillDetail:
    """Raises ``contracts.BatchExportBackfillNotFoundError`` unless the team has this backfill."""
    return _import_backfills().get_backfill(team_id, export_id, backfill_id)


def create_batch_export_backfill(
    team_id: int, export_id: UUID, *, start_at: object, end_at: object
) -> contracts.BatchExportBackfillStart:
    """Start a backfill. ``start_at`` and ``end_at`` arrive as the request sent them.

    Daily and weekly exports take ISO 8601 dates, other intervals ISO 8601 datetimes with a time zone.
    Raises ``contracts.BatchExportNotFoundError``, ``contracts.InvalidBackfillRequestError`` or
    ``contracts.TooManyConcurrentBackfillsError``.
    """
    return _import_backfills().create_backfill(team_id, export_id, start_at, end_at)


def cancel_batch_export_backfill(team_id: int, export_id: UUID, backfill_id: UUID) -> None:
    """Cancel a starting or running backfill and its runs in progress.

    Raises ``contracts.InvalidBackfillRequestError`` in any other status.
    """
    _import_backfills().cancel_backfill(team_id, export_id, backfill_id)
