"""
Model-class wiring for batch_exports.

Re-exports the BatchExportRun model cross-product consumers read. Light (Django model).

batch_exports is not on the watched-models allowance (``MODEL_CROSSINGS``), so this
re-export is an unsanctioned crossing, not a sanctioned one. Its one consumer is the
failed-runs block of the data_warehouse overview, which ``facade.api.list_latest_failed_runs``
replaces. This module goes when that consumer moves.
"""

from products.batch_exports.backend.models.batch_export import BatchExportRun

__all__ = ["BatchExportRun"]
