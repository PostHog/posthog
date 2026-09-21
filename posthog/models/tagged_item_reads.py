"""Chooses which pointer tag reads use while the generic pointer rolls out.

Writes fill both pointers either way, so the flag can move in either direction at any time.
Reads outside a team scope, such as Celery and Temporal jobs, stay on the legacy pointer.
"""

import time
import threading
from typing import Any

from django.db import models
from django.db.models import Q

from posthog.dataclasses import frozen
from posthog.models.scoping import get_current_team_id
from posthog.models.tagged_item_registry import content_type_for_entry, require_taggable
from posthog.ph_client import feature_enabled_or_false

GENERIC_READS_FLAG = "tagged-item-generic-reads"

# One query build reads the pointer several times: the relation's column, its join fields, and its
# join restriction. They must agree, so each team's decision is held briefly, not evaluated per call.
_DECISION_TTL_SECONDS = 30.0
_MAX_CACHED_TEAMS = 50_000
_decisions: dict[int, "_Decision"] = {}
_decisions_lock = threading.Lock()


@frozen
class TagReadPointer:
    """The TaggedItem columns that point at the objects of one taggable model."""

    object_column: str
    content_type_id: int | None

    def for_model(self) -> Q:
        """Rows that tag any object of the model."""
        if self.content_type_id is None:
            # nosemgrep: orm-field-injection -- the name comes from the closed TAGGABLE_MODELS registry, never from input
            return Q(**{f"{self.object_column}__isnull": False})
        return Q(content_type_id=self.content_type_id)

    def matching(self, value: Any, lookup: str = "exact") -> Q:
        """Rows whose tagged object key matches `value` with `lookup`."""
        # nosemgrep: orm-field-injection -- the name comes from the closed TAGGABLE_MODELS registry, never from input
        condition = Q(**{f"{self.object_column}__{lookup}": value})
        if self.content_type_id is None:
            return condition
        return condition & Q(content_type_id=self.content_type_id)


@frozen
class _Decision:
    evaluated_at: float
    enabled: bool


def generic_reads_enabled() -> bool:
    """Whether tag reads in the current team scope use the generic pointer."""
    team_id = get_current_team_id()
    if team_id is None:
        return False
    now = time.monotonic()
    cached = _decisions.get(team_id)
    if cached is not None and now - cached.evaluated_at < _DECISION_TTL_SECONDS:
        return cached.enabled
    enabled = feature_enabled_or_false(
        GENERIC_READS_FLAG,
        str(team_id),
        groups={"project": str(team_id)},
        group_properties={"project": {"id": str(team_id)}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
    with _decisions_lock:
        if len(_decisions) >= _MAX_CACHED_TEAMS:
            _decisions.clear()
        _decisions[team_id] = _Decision(evaluated_at=now, enabled=enabled)
    return enabled


def clear_generic_reads_cache() -> None:
    """Forget every held decision, so the next read evaluates the flag again."""
    with _decisions_lock:
        _decisions.clear()


def tag_read_pointer(model: type[models.Model]) -> TagReadPointer:
    """The columns that tag reads for `model` use in the current team scope."""
    entry = require_taggable(model)
    if generic_reads_enabled():
        return TagReadPointer(object_column=entry.object_field, content_type_id=content_type_for_entry(entry).id)
    return TagReadPointer(object_column=f"{entry.legacy_field}_id", content_type_id=None)
