"""
Temporal registration wiring for data_modeling.

Re-exports the workflow and activity lists the Temporal worker bootstrap loads, and the
activity helpers that tests in other products exercise.

Imports temporalio and the activity modules, so it must only be imported off the
``django.setup()`` path.
"""

from products.data_modeling.backend.temporal import (
    ACTIVITIES,
    SEMANTIC_ENRICHMENT_ACTIVITIES,
    SEMANTIC_ENRICHMENT_WORKFLOWS,
    WORKFLOWS,
)
from products.data_modeling.backend.temporal.activities.materialize_view_managed_warehouse import (
    _compile_hogql_for_ducklake as compile_hogql_for_ducklake,
)
from products.data_modeling.backend.temporal.testing import check_unique_key, upsert_batch

__all__ = [
    "ACTIVITIES",
    "SEMANTIC_ENRICHMENT_ACTIVITIES",
    "SEMANTIC_ENRICHMENT_WORKFLOWS",
    "WORKFLOWS",
    "check_unique_key",
    "compile_hogql_for_ducklake",
    "upsert_batch",
]
