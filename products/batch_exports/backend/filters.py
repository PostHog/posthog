"""
The event filters a batch export stores, and the checks they must pass on write.

This module imports no framework and no Temporal code, because the facade imports it and the
facade is on the ``django.setup()`` path. ``service.py`` imports ``temporalio``, so the checks
cannot live there.
"""

from products.batch_exports.backend.facade.contracts import InvalidBatchExportFilters
from products.batch_exports.backend.facade.enums import SUPPORTED_FILTER_TYPES, SUPPORTED_FILTER_TYPES_DISPLAY


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
