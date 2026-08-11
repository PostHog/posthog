"""Lives outside ``temporal/`` so the facade can import it at module level. Importing
anything under ``temporal/`` runs that package's ``__init__``, which loads the summarize
workflow, which imports the customer_analytics facade, which imports the conversations
facade.
"""

from __future__ import annotations

from datetime import date


def build_channel_summary_workflow_id(*, account_id: str, cadence: str, period_start: date) -> str:
    """Both the scheduled coordinator and the opt-in backfill start this workflow. They must
    derive the same id, or the two paths summarize a period twice."""
    return f"account-channel-summary-{account_id}-{cadence}-{period_start.isoformat()}"
