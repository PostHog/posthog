"""
The event filters a batch export stores, and the checks they must pass on write.

This module imports no framework and no Temporal code, so the DRF serializer and the facade
share one set of checks. ``service.py`` imports ``temporalio``, so the checks cannot live
there: the facade is on the ``django.setup()`` path.
"""

from products.batch_exports.backend.facade.contracts import InvalidBatchExportFilters

# Single source of truth for the serialized filter `type` values we accept. Enforced at write
# time by `validate_batch_export_filters` and at query time by `compose_filters_clause`.
SUPPORTED_FILTER_TYPES = {"event", "person", "hogql"}

# Quoted, sorted rendering of the supported filter types for user-facing messages.
SUPPORTED_FILTER_TYPES_DISPLAY = ", ".join(repr(t) for t in sorted(SUPPORTED_FILTER_TYPES))


def validate_batch_export_filters(filters: object) -> None:
    """Raise ``InvalidBatchExportFilters`` unless ``filters`` is None or a list of supported filters."""
    if filters is None:
        return

    if not isinstance(filters, list):
        raise InvalidBatchExportFilters("'filters' should be an array of filters")

    for filter in filters:
        if not isinstance(filter, dict):
            raise InvalidBatchExportFilters("Each filter must be an object")

        if any(key in filter for key in ("data_interval_start", "data_interval_end")):
            raise InvalidBatchExportFilters(
                "'data_interval_start' and 'data_interval_end' are run attributes and not 'filters'."
                " Trigger a backfill if you wish to manually control which periods to batch export."
            )

        if filter.get("type") not in SUPPORTED_FILTER_TYPES:
            raise InvalidBatchExportFilters(
                f"Each filter must have a 'type' of one of: {SUPPORTED_FILTER_TYPES_DISPLAY}"
            )
