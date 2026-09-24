from datetime import datetime
from functools import partial
from uuid import UUID

from django.db import transaction

from products.customer_analytics.backend.logic.custom_property_source_disabled_notice import notify_source_auto_disabled
from products.customer_analytics.backend.models import CustomPropertySource

MAX_CONSECUTIVE_SYNC_FAILURES = 5


def record_sync_success(source: CustomPropertySource, *, finished_at: datetime | None) -> None:
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
    transaction.on_commit(
        partial(
            notify_source_auto_disabled,
            team_id=team_id,
            source_id=source_id,
            disable_event_id=disable_event_id,
        )
    )
