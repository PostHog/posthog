"""The health lifecycle both custom-property run recorders share.

Each path decides on its own when a logical sync is over — the account path waits for both
segments, the person path dedupes a warehouse job's retries. What they share is the failure
streak, the auto-disable threshold, and telling the sync owner once when a source crosses it.
Keeping the threshold here is the point: two private copies drifted apart is how one path
disables at five failures and the other at some other number.
"""

from datetime import datetime
from functools import partial
from uuid import UUID

from django.db import transaction

from products.customer_analytics.backend.logic.custom_property_source_disabled_notice import notify_source_auto_disabled
from products.customer_analytics.backend.models import CustomPropertySource

MAX_CONSECUTIVE_SYNC_FAILURES = 5


def record_sync_success(source: CustomPropertySource, *, finished_at: datetime | None) -> None:
    """Clear the source's failure streak and stamp when it last synced."""
    source.last_synced_at = finished_at
    source.last_sync_error = None
    source.consecutive_failures = 0
    source.save(update_fields=["last_synced_at", "last_sync_error", "consecutive_failures", "updated_at"])


def record_sync_failure(
    source: CustomPropertySource,
    *,
    error: str | None,
    disable_event_id: str,
    count_failure: bool = True,
) -> bool:
    """Fold a failed logical sync onto the source. Returns True when this failure disabled it.

    ``count_failure`` is False for a failure the caller already counted, such as a person-path
    activity retry re-reporting a job that failed before. ``disable_event_id`` names the run that
    could disable the source, so the owner hears about one disablement once however many times
    the recorder runs for it.
    """
    was_enabled = source.is_enabled
    if count_failure:
        source.consecutive_failures = (source.consecutive_failures or 0) + 1
    source.last_sync_error = error
    if source.consecutive_failures >= MAX_CONSECUTIVE_SYNC_FAILURES:
        source.is_enabled = False
    source.save(update_fields=["consecutive_failures", "last_sync_error", "is_enabled", "updated_at"])

    auto_disabled = was_enabled and not source.is_enabled
    if auto_disabled:
        _schedule_owner_notice(team_id=source.team_id, source_id=source.id, disable_event_id=disable_event_id)
    return auto_disabled


def _schedule_owner_notice(*, team_id: int, source_id: UUID, disable_event_id: str) -> None:
    """Deliver after the source transaction commits.

    The account path holds row locks across this call, and delivery reads users, access control
    and tasks. Running it inside would hold those locks for the whole round trip, and a delivery
    that raised would roll the auto-disable back with it.
    """
    transaction.on_commit(
        partial(
            notify_source_auto_disabled,
            team_id=team_id,
            source_id=source_id,
            disable_event_id=disable_event_id,
        )
    )
