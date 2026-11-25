from collections.abc import Sequence
from datetime import UTC, datetime

from django.db.models import Q, QuerySet, Sum
from django.db.models.functions import Coalesce

from products.batch_exports.backend.models.batch_export import (
    BatchExport,
    BatchExportDestination,
    BatchExportOnDemand,
    BatchExportRun,
)

NON_BILLABLE_DESTINATIONS = [
    BatchExportDestination.Destination.HTTP,
    BatchExportDestination.Destination.WORKFLOWS,
]

# Runs of the HogQL model are free while the model is in closed beta.
# TODO: Remove this once the beta ends, so that its rows become billable like any other model's.
NON_BILLABLE_MODELS = [BatchExport.Model.HOGQL]

# From this instant, rows a batch export delivers bill on the warehouse `rows_synced` meter
# instead of `rows_exported`. A run that finishes exactly at the cutover bills on `rows_synced`.
UNIFIED_PIPELINES_PRICING_START: datetime = datetime(2027, 2, 1, tzinfo=UTC)


def exports_bill_as_rows_synced(at: datetime) -> bool:
    return at >= UNIFIED_PIPELINES_PRICING_START


def exclude_non_billable_runs(runs: QuerySet[BatchExportRun]) -> QuerySet[BatchExportRun]:
    """Drop the runs we do not bill from a `BatchExportRun` queryset.

    Each condition is checked against both parents, as a run belongs to either a
    `BatchExport` or a `BatchExportOnDemand`. The unset parent joins to nulls, which match
    neither `exclude`, so the run is filtered on its own parent only.
    """
    return (
        runs.filter(Q(batch_export__deleted=False) | Q(batch_export_on_demand__deleted=False))
        .exclude(batch_export__destination__type__in=NON_BILLABLE_DESTINATIONS)
        .exclude(batch_export_on_demand__destination__type__in=NON_BILLABLE_DESTINATIONS)
        .exclude(batch_export__model__in=NON_BILLABLE_MODELS)
        .exclude(batch_export_on_demand__model__in=NON_BILLABLE_MODELS)
    )


def is_billable_run(run: BatchExportRun) -> bool:
    """Check if a single run counts towards billing, as `exclude_non_billable_runs` does."""
    export = run.batch_export or run.batch_export_on_demand
    if export is None or export.deleted:
        return False
    if export.destination.type in NON_BILLABLE_DESTINATIONS:
        return False
    return export.model not in NON_BILLABLE_MODELS


def count_billable_rows_exported(team_ids: Sequence[int], since: datetime) -> int:
    """Sum the rows the teams exported through billable runs that finished at or after `since`."""
    # Runs are only indexed on their parent foreign keys, so narrow each parent through its own
    # export ids. One OR across both parents' team_id would scan the whole run history instead.
    by_parent = (
        Q(batch_export_id__in=BatchExport.objects.filter(team_id__in=team_ids).values("id")),
        Q(
            batch_export_on_demand_id__in=BatchExportOnDemand.objects.unscoped()
            .filter(team_id__in=team_ids)
            .values("id")
        ),
    )
    total = 0
    for parent in by_parent:
        completed_runs = BatchExportRun.objects.filter(
            parent, finished_at__gte=since, status=BatchExportRun.Status.COMPLETED
        )
        total += exclude_non_billable_runs(completed_runs).aggregate(total=Coalesce(Sum("records_completed"), 0))[
            "total"
        ]
    return total
