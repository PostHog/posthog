from collections.abc import Sequence

from django.utils import timezone

from products.ai_training.backend.config import privacy_enabled
from products.ai_training.backend.tasks.tasks import resolve_person_training_sessions_task

# Matches the lookup's own batch, so one task runs one replay scan per page of sessions.
PERSON_LOOKUP_DISTINCT_IDS_PER_TASK = 1000


def queue_person_training_deletion(team_id: int, distinct_ids: Sequence[str]) -> None:
    """Hand the replay session lookup for ``distinct_ids`` to a background task.

    The lookup scans ClickHouse, which can be at capacity for minutes at a time. The caller only
    waits for the task to be queued, so a busy cluster delays the training deletion and does not
    fail the person deletion. The task carries the distinct IDs, because the caller deletes the
    person that owns them.
    """
    if not privacy_enabled() or not distinct_ids:
        return
    started_before = timezone.now().isoformat()
    unique = sorted(set(distinct_ids))
    for offset in range(0, len(unique), PERSON_LOOKUP_DISTINCT_IDS_PER_TASK):
        resolve_person_training_sessions_task.delay(
            team_id, unique[offset : offset + PERSON_LOOKUP_DISTINCT_IDS_PER_TASK], started_before
        )
