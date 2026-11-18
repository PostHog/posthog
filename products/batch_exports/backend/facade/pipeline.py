"""
Export-pipeline wiring for batch_exports.

Re-exports the stream transformers that the warehouse_sources Temporal writers reuse, so a
data import and a batch export serialize records the same way. The destination clients live
in ``facade/destinations/``, one module per destination.

Importing this module loads pyarrow, so keep it off the ``django.setup()`` path. See
``posthog/test/repo_invariants/test_startup_import_budget.py``.
"""

from products.batch_exports.backend.temporal.pipeline.transformer import CSVStreamTransformer, ParquetStreamTransformer

__all__ = [
    "CSVStreamTransformer",
    "ParquetStreamTransformer",
]
