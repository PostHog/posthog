"""The skeleton shared alert tables, as a source adapter sees them.

A source reads a batch of checks, reports what it decided, and can copy its own configurations
in. It never holds one of these rows, so every write and every scheduling rule has one home.
"""

from products.alerts.backend.logic.platform_lifecycle import due_checks, record_outcomes, slot_of, upsert_configuration

__all__ = [
    "due_checks",
    "record_outcomes",
    "slot_of",
    "upsert_configuration",
]
