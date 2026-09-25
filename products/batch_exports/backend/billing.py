from django.db.models import Q, QuerySet

from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination, BatchExportRun

NON_BILLABLE_DESTINATIONS = [
    BatchExportDestination.Destination.HTTP,
    BatchExportDestination.Destination.WORKFLOWS,
]

# Runs of the HogQL model are free while the model is in closed beta.
# TODO: Remove this once the beta ends, so that its rows become billable like any other model's.
NON_BILLABLE_MODELS = [BatchExport.Model.HOGQL]


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
