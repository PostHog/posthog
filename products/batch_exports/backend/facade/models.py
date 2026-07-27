"""
Model-class wiring for batch_exports.

Re-exports the BatchExportRun model cross-product consumers read. Light (Django model).
"""

from products.batch_exports.backend.models.batch_export import BatchExportRun

__all__ = ["BatchExportRun"]
