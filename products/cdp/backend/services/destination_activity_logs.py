"""Mask values in activity log rows written before the log masked their fields.

Until a field was added to the masked-fields registry, each change to it stored the old and
new values in plain text. For hog functions that included credentials in `inputs`, and for
workflows the secret inputs in `actions`. Read-time masking hides the rows from the activity
log API, but the `system.activity_logs` HogQL table and the search filter read `detail`
directly, so the rows need rewriting.

Masking uses `ActivityLog.safe_detail`, which keeps the field name and change action.
A row that is already masked is left untouched, so a rerun changes nothing.
"""

from collections.abc import Iterator
from typing import Optional
from uuid import UUID

from django.db.models import Q

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityLog, field_with_masked_contents, read_masked_fields


@frozen
class ActivityLogScope:
    team_id: Optional[int] = None
    batch_size: int = 500


@frozen
class ActivityLogMaskCount:
    rows: int
    teams: int


def _masked_fields() -> dict[str, set[str]]:
    fields: dict[str, set[str]] = {}
    for registry in (field_with_masked_contents, read_masked_fields):
        for model_scope, names in registry.items():
            fields.setdefault(model_scope, set()).update(names)
    return fields


def _candidate_ids(scope: ActivityLogScope) -> list[UUID]:
    # Containment on `detail` uses the GIN index. Adding an ORDER BY or LIMIT here lets the
    # planner walk the primary key instead, which scans the whole table and times out in production.
    # The change `type` keeps common field names such as `name` from matching millions of rows.
    ids: list[UUID] = []
    for model_scope, fields in _masked_fields().items():
        field_filter = Q()
        for field in sorted(fields):
            field_filter |= Q(detail__contains={"changes": [{"type": model_scope, "field": field}]})
        queryset = ActivityLog.objects.filter(field_filter, scope=model_scope)
        if scope.team_id is not None:
            queryset = queryset.filter(team_id=scope.team_id)
        ids.extend(queryset.values_list("id", flat=True))
    return ids


def _unmasked_batches(scope: ActivityLogScope) -> Iterator[list[ActivityLog]]:
    ids = _candidate_ids(scope)
    for start in range(0, len(ids), scope.batch_size):
        batch = ActivityLog.objects.filter(id__in=ids[start : start + scope.batch_size]).only(
            "id", "team_id", "scope", "detail"
        )
        yield [log for log in batch if log.safe_detail != log.detail]


def count_unmasked_activity_logs(scope: ActivityLogScope) -> ActivityLogMaskCount:
    rows = 0
    teams: set[int] = set()
    for batch in _unmasked_batches(scope):
        rows += len(batch)
        teams.update(log.team_id for log in batch if log.team_id is not None)
    return ActivityLogMaskCount(rows=rows, teams=len(teams))


def mask_activity_logs(scope: ActivityLogScope) -> int:
    masked = 0
    for batch in _unmasked_batches(scope):
        for log in batch:
            log.detail = log.safe_detail
        ActivityLog.objects.bulk_update(batch, ["detail"])
        masked += len(batch)
    return masked
