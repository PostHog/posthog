"""
Public facade for autoresearch.

Every consumer — this product's own presentation layer included — reaches autoresearch
data and behavior through this module. Functions take and return the frozen contracts in
``contracts.py``; ORM rows never leave.

Scope is set at the entry boundary, so every read and write here takes ``team_id`` and
filters on it. Business rules live in the modules behind this facade, not in the views.
"""

AUTORESEARCH_FLAG = "autoresearch"


def flag_key() -> str:
    """The feature flag that gates every autoresearch surface."""
    return AUTORESEARCH_FLAG
