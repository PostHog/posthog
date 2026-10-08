"""Field snapshots of a model instance, and the activity log diff between two of them.

A product facade returns frozen contracts, not models. It captures a snapshot inside its service, where
it holds the row, and returns the snapshot on the contract. The caller then logs the diff with
`log_activity_change`. `changes_between` uses the same capture and diff, so both paths log the same changes.
"""

from __future__ import annotations

import copy
import json
import hashlib
from collections.abc import Sequence
from dataclasses import field
from typing import Any
from uuid import UUID

from django.conf import settings
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    ActivityLog,
    ActivityScope,
    AuditableScope,
    Change,
    Detail,
    MaskedChange,
    Trigger,
    _report_activity_log_write_failure,
    common_field_exclusions,
    field_exclusions,
    field_name_overrides,
    field_with_masked_contents,
    key_masked_fields,
    log_activity,
    mask_change_values,
    safely_get_field_value,
)
from posthog.models.activity_logging.actor import ActivityActor
from posthog.models.user import User


def _digest(value: Any) -> str:
    # The same canonical form `mask_change_values` compares, so equal values give equal digests.
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _masked_value(scope: AuditableScope, name: str, value: Any, is_empty: bool) -> Any:
    if value is None or is_empty:
        # An empty value tells nothing, and `mask_change_values` needs `{}` and `""` to stay as they are.
        return value
    if name in key_masked_fields.get(scope, []) and isinstance(value, dict):
        return {key: _digest(item) for key, item in value.items()}
    return _digest(value)


@frozen
class CapturedField:
    name: str
    value: Any = field(repr=False)
    is_empty: bool
    masked: bool


@frozen
class ActivitySnapshot:
    """The logged field values of one instance, read when the snapshot is taken.

    A masked field holds a digest, never its value, so the plaintext does not leave the service that
    took the snapshot. The diff still sees that the field changed.
    """

    scope: AuditableScope
    fields: tuple[CapturedField, ...]

    def __repr__(self) -> str:
        names = ", ".join(captured.name for captured in self.fields)
        return f"ActivitySnapshot(scope={self.scope!r}, fields=[{names}])"

    @classmethod
    def of(cls, scope: AuditableScope, instance: models.Model) -> ActivitySnapshot:
        # Copy the values, so a later in-place edit of the instance does not change this snapshot.
        return cls._capture(scope, field_source=instance, instances=[instance], detach=True)[0]

    @classmethod
    def _capture(
        cls,
        scope: AuditableScope,
        *,
        field_source: models.Model,
        instances: Sequence[models.Model | None],
        detach: bool,
    ) -> list[ActivitySnapshot]:
        """Read each field of `field_source` from every instance in turn, so a diff of two instances runs
        its queries in the same order as reading them field by field."""
        model_fields = field_source._meta.get_fields()
        # get_fields() lists a GenericRelation last, as a private field, but lists the reverse
        # foreign key it replaced first. Keep the old position so the diff order does not change.
        model_fields = sorted(model_fields, key=lambda f: not isinstance(f, GenericRelation))
        excluded_fields = field_exclusions.get(scope, []) + common_field_exclusions
        masked_fields = field_with_masked_contents.get(scope, [])
        kept_fields = [f for f in model_fields if f.name not in excluded_fields]
        kept_field_names = [f.name for f in kept_fields]

        captured: list[list[CapturedField]] = [[] for _ in instances]
        for model_field in kept_fields:
            values = [safely_get_field_value(instance, model_field.name) for instance in instances]

            name = model_field.name
            if name == "tagged_items":
                name = "tags"  # Or the UI needs to be coupled to this internal backend naming.

            if name == "dashboards" and "dashboard_tiles" in kept_field_names:
                # Only process dashboard_tiles when it is present. It supersedes dashboards.
                continue

            if scope == "Insight" and name == "dashboard_tiles":
                # The API exposes this as dashboards and that's what the activity describers expect.
                name = "dashboards"

            # A reverse foreign key has no empty_values, so an empty list counts as a value. A
            # GenericRelation inherits them from Field, and keeps the reverse foreign key behavior.
            empty_values = (
                None if isinstance(model_field, GenericRelation) else getattr(model_field, "empty_values", None)
            )
            masked = name in masked_fields

            for instance_fields, value in zip(captured, values):
                is_empty = value is None or (empty_values is not None and value in empty_values)
                if masked:
                    value = _masked_value(scope, name, value, is_empty)
                elif detach and not isinstance(value, models.Model):
                    value = copy.deepcopy(value)
                instance_fields.append(CapturedField(name=name, value=value, is_empty=is_empty, masked=masked))

        return [cls(scope=scope, fields=tuple(instance_fields)) for instance_fields in captured]


def diff_snapshots(scope: AuditableScope, before: ActivitySnapshot, after: ActivitySnapshot) -> list[Change]:
    """The changes from `before` to `after`, over the fields of `after`."""
    if before.scope != scope or after.scope != scope:
        raise ValueError(f"Cannot diff snapshots of {before.scope} and {after.scope} as {scope}")

    before_fields = {captured.name: captured for captured in before.fields}
    changes: list[Change] = []
    for right in after.fields:
        left = before_fields.get(right.name)
        left_value = left.value if left is not None else None
        left_is_empty = left.is_empty if left is not None else True

        change_values = (
            mask_change_values(scope, right.name, left_value, right.value)
            if right.masked
            else MaskedChange(before=left_value, after=right.value)
        )
        display_name = field_name_overrides.get(scope, {}).get(right.name, right.name)

        if left_is_empty and right.is_empty:
            pass  # could be {} vs None
        elif left_is_empty:
            changes.append(Change(type=scope, field=display_name, action="created", after=change_values.after))
        elif right.is_empty:
            changes.append(Change(type=scope, field=display_name, action="deleted", before=change_values.before))
        elif left_value != right.value:
            changes.append(
                Change(
                    type=scope,
                    field=display_name,
                    action="changed",
                    before=change_values.before,
                    after=change_values.after,
                )
            )

    return changes


def diff_instances(scope: AuditableScope, previous: models.Model, current: models.Model) -> list[Change]:
    """The changes from `previous` to `current`, over the fields of `current`."""
    # Both instances are read once and diffed at once, so the values need no copy.
    before, after = ActivitySnapshot._capture(scope, field_source=current, instances=[previous, current], detach=False)
    return diff_snapshots(scope, before, after)


def log_activity_change(
    *,
    actor: ActivityActor,
    scope: ActivityScope,
    item_id: int | str | UUID,
    activity: str,
    name: str | None = None,
    before: ActivitySnapshot | None,
    after: ActivitySnapshot | None,
    detail_type: str | None = None,
    trigger: Trigger | None = None,
    context: ActivityContextBase | None = None,
) -> ActivityLog | None:
    """Log one change. The detail lists the field changes when both snapshots are given, and none otherwise.

    `log_activity` reports and drops a failed write, so this returns None then, as it does for an
    update with no changes.
    """
    changes: list[Change] | None = None
    if before is not None and after is not None:
        try:
            changes = diff_snapshots(scope, before, after)
        except Exception as e:
            _report_activity_log_write_failure(
                e,
                {"team": actor.team_id, "organization_id": actor.organization_id, "scope": scope, "activity": activity},
                deferred=False,
            )
            if settings.TEST:
                raise
            return None

    user = User.objects.filter(pk=actor.user_id).first() if actor.user_id is not None else None
    return log_activity(
        organization_id=actor.organization_id,
        team_id=actor.team_id,
        user=user,
        was_impersonated=actor.was_impersonated,
        item_id=item_id,
        scope=scope,
        activity=activity,
        detail=Detail(name=name, type=detail_type, changes=changes, trigger=trigger, context=context),
    )
