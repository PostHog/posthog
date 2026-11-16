"""Reads and writes behind the actions API: the list, one action, a create, an update and bulk tag changes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from django.db.models import Prefetch, Q, QuerySet

from posthog.models import TaggedItem
from posthog.models.utils import strict_fetch
from posthog.paging import Page

from products.actions.backend.facade.contracts import (
    ActionListAccess,
    ActionListFilters,
    ActionNotFound,
    ActionOrdering,
    ActionWrite,
    ActionWriteField,
)
from products.actions.backend.models.action import Action

if TYPE_CHECKING:
    from posthog.models import User

# Last calculated first, then by name: the order the actions page and the taxonomic filter read the list in.
DEFAULT_ORDERING = ("-last_calculated_at", "name")

# The model attribute each plain write field sets. Steps, pinning, tags and the folder take their own paths.
_MODEL_FIELDS = {
    ActionWriteField.NAME: "name",
    ActionWriteField.DESCRIPTION: "description",
    ActionWriteField.POST_TO_SLACK: "post_to_slack",
    ActionWriteField.SLACK_MESSAGE_FORMAT: "slack_message_format",
    ActionWriteField.DELETED: "deleted",
    ActionWriteField.LAST_CALCULATED_AT: "last_calculated_at",
}


def with_relations(queryset: QuerySet[Action]) -> QuerySet[Action]:
    """The queryset with the creator and the tags loaded, the relations an API response reads."""
    return queryset.select_related("created_by").prefetch_related(
        Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags")
    )


def _order_by(ordering: ActionOrdering | None) -> tuple[str, ...]:
    if ordering is None:
        return DEFAULT_ORDERING
    prefix = "-" if ordering.descending else ""
    if ordering.field == "created_by":
        fields = [f"{prefix}created_by__first_name", f"{prefix}created_by__last_name"]
    else:
        fields = [f"{prefix}{ordering.field}"]
    if ordering.field != "name":
        fields.append("name")
    return tuple(fields)


def _visible_to(queryset: QuerySet[Action], access: ActionListAccess | None) -> QuerySet[Action]:
    # The same narrowing `UserAccessControl.filter_queryset_by_access_level` applies to a queryset list.
    if access is None:
        return queryset
    if access.only_allowed:
        return queryset.filter(Q(id__in=access.allowed_ids) | Q(created_by_id=access.viewer_id))
    if access.blocked_ids:
        return queryset.exclude(Q(id__in=access.blocked_ids) & ~Q(created_by_id=access.viewer_id))
    return queryset


def list_details(
    *,
    team_id: int,
    filters: ActionListFilters,
    access: ActionListAccess | None,
    offset: int,
    limit: int | None,
) -> Page[Action]:
    queryset = _visible_to(Action.objects.filter(team_id=team_id, deleted=False), access)
    if filters.search:
        queryset = queryset.filter(name__icontains=filters.search)
    if filters.created_by_ids:
        queryset = queryset.filter(created_by_id__in=filters.created_by_ids)
    if filters.tags:
        # The tag join yields a row per matching tag, so an action with two of them would come back twice.
        queryset = queryset.filter(tagged_items__tag__name__in=filters.tags).distinct()
    queryset = strict_fetch(with_relations(queryset.order_by(*_order_by(filters.ordering))))

    # The list without a limit is the hot path the taxonomic filter shares, so it derives the count from
    # the rows it returns rather than paying for a count query.
    if limit is None:
        actions = list(queryset[offset:] if offset else queryset)
        return Page(results=actions, count=offset + len(actions))
    count = queryset.count()
    return Page(results=list(queryset[offset : offset + limit]), count=count)


def get_detail(*, team_id: int, action_id: int) -> Action:
    try:
        return with_relations(Action.objects.filter(team_id=team_id)).get(pk=action_id)
    except Action.DoesNotExist:
        raise ActionNotFound(f"Action {action_id} does not exist") from None


def count_live(*, team_id: int) -> int:
    return Action.objects.filter(team_id=team_id, deleted=False).count()


def colliding_action_id(*, team_id: int, name: str, exclude_action_id: int | None) -> int | None:
    queryset = Action.objects.filter(team_id=team_id, name=name, deleted=False)
    if exclude_action_id is not None:
        queryset = queryset.exclude(id=exclude_action_id)
    return next(iter(queryset[:1].values_list("id", flat=True)), None)


def _set_tags(action: Action, tags: Sequence[str]) -> None:
    from posthog.api.tagged_item import (  # noqa: PLC0415 — keeps the DRF API stack off the facade's import path
        replace_tags_on_object,
    )

    action.prefetched_tags = replace_tags_on_object(list(tags), action)  # type: ignore[attr-defined]


def create(*, team_id: int, created_by: User | None, write: ActionWrite) -> Action:
    fields: dict[str, Any] = {
        model_field: getattr(write, write_field)
        for write_field, model_field in _MODEL_FIELDS.items()
        if write_field in write.fields_set
    }
    if ActionWriteField.STEPS in write.fields_set:
        fields["steps_json"] = [asdict(step) for step in write.steps]
    if ActionWriteField.PINNED_AT in write.fields_set:
        fields["pinned_at"] = write.pinned_at
    if ActionWriteField.CREATE_IN_FOLDER in write.fields_set:
        fields["_create_in_folder"] = write.create_in_folder
    action = Action.objects.create(team_id=team_id, created_by=created_by, **fields)
    if ActionWriteField.TAGS in write.fields_set:
        _set_tags(action, write.tags)
    return action


def update(*, action: Action, write: ActionWrite) -> Action:
    for write_field, model_field in _MODEL_FIELDS.items():
        if write_field in write.fields_set:
            setattr(action, model_field, getattr(write, write_field))
    if ActionWriteField.STEPS in write.fields_set:
        action.steps_json = [asdict(step) for step in write.steps]
    if ActionWriteField.PINNED_AT in write.fields_set:
        if write.pinned_at is None:
            action.pinned_at = None
        elif action.pinned_at is None:
            action.pinned_at = datetime.now(UTC)
    if ActionWriteField.CREATE_IN_FOLDER in write.fields_set:
        action._create_in_folder = write.create_in_folder
    action.save()
    if ActionWriteField.TAGS in write.fields_set:
        _set_tags(action, write.tags)
    return action


def change_tags(
    *, team_id: int, action_ids: Sequence[int], tag_action: str, tags: Sequence[str]
) -> list[dict[str, Any]]:
    from posthog.api.tagged_item import (  # noqa: PLC0415 — keeps the DRF API stack off the facade's import path
        apply_bulk_tag_changes,
    )

    actions = Action.objects.filter(team_id=team_id, id__in=list(action_ids)).prefetch_related(
        Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags")
    )
    by_id = {action.id: action for action in actions}
    return apply_bulk_tag_changes(
        [by_id[action_id] for action_id in action_ids if action_id in by_id], tag_action, list(tags)
    )
