"""
Temporal registration wiring for data_modeling.

Re-exports the workflow and activity lists the Temporal worker bootstrap loads. Helpers for
tests in other products live in ``facade/testing.py``.

Imports temporalio and the activity modules, so it must only be imported off the
``django.setup()`` path.
"""

from products.data_modeling.backend.temporal import (
    ACTIVITIES,
    SEMANTIC_ENRICHMENT_ACTIVITIES,
    SEMANTIC_ENRICHMENT_WORKFLOWS,
    WORKFLOWS,
)

__all__ = [
    "ACTIVITIES",
    "SEMANTIC_ENRICHMENT_ACTIVITIES",
    "SEMANTIC_ENRICHMENT_WORKFLOWS",
    "WORKFLOWS",
]
