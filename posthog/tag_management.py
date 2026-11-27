from collections.abc import Collection
from copy import copy
from itertools import batched
from typing import Literal
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, router
from django.db.models import Count, Exists, OuterRef, Q

from posthog.dataclasses import frozen
from posthog.models import Tag, TaggedItem
from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    Change,
    Detail,
    LogActivityEntry,
    bulk_log_activity,
    defer_activity_log_events,
    log_activity,
)
from posthog.models.activity_logging.model_activity import ActingUserContext, get_was_impersonated
from posthog.models.signals import model_activity_signal
from posthog.models.tag import tag_assignment_transaction, tagify
from posthog.models.user import User

MAX_SYNC_TAG_ASSIGNMENTS = 10_000


@frozen
class TagMergePreview:
    source_count: int
    target_count: int
    overlap_count: int
    result_count: int
    tag: Tag


@frozen
class TagMergeResult:
    moved_count: int
    overlap_count: int
    usage_count: int
    tag: Tag


@frozen(slots=False)
class TagManagementContext(ActivityContextBase):
    operation: Literal["rename", "merge", "delete"]
    source_id: str
    source_name: str
    target_id: str | None = None
    target_name: str | None = None
    moved_count: int = 0
    overlap_count: int = 0
    usage_count: int = 0
    outcome: Literal["completed"] = "completed"


def _get_tags(
    team_id: int, tag_ids: Collection[UUID], *, using: str | None = None, lock: bool = False
) -> dict[UUID, Tag]:
    queryset = (
        Tag.objects.using(using)
        .filter(team_id=team_id, id__in=tag_ids)
        .exclude(name__startswith="project-group:")
        .select_related("team")
        .order_by("id")
    )
    if lock:
        queryset = queryset.select_for_update(of=("self",))
    tags = {tag.id: tag for tag in queryset}
    if tags.keys() != set(tag_ids):
        raise Tag.DoesNotExist("Tag not found. Refresh the list and choose an available tag.")
    return tags


def _validate_distinct_tags(source_id: UUID, target_id: UUID) -> None:
    if source_id == target_id:
        raise ValidationError("Choose a different destination tag.")


def _validate_sync_assignment_count(tag: Tag, *, using: str) -> None:
    assignments = TaggedItem.objects.using(using).filter(team_id=tag.team_id, tag_id=tag.id)
    if assignments[: MAX_SYNC_TAG_ASSIGNMENTS + 1].count() > MAX_SYNC_TAG_ASSIGNMENTS:
        raise ValidationError(
            f"This tag exceeds the {MAX_SYNC_TAG_ASSIGNMENTS:,}-assignment limit. "
            "Remove assignments before renaming or merging it.",
            code="tag_assignment_limit",
        )


def _get_preview(source: Tag, target: Tag, *, using: str | None = None) -> TagMergePreview:
    items = TaggedItem.objects.using(using).filter(team_id=source.team_id)
    matching_target = items.filter(tag_id=target.id, content_type_id=OuterRef("content_type_id")).filter(
        Q(object_id=OuterRef("object_id")) | Q(object_uuid=OuterRef("object_uuid"))
    )
    is_source = Q(tag_id=source.id)
    counts = (
        items.filter(tag_id__in=[source.id, target.id])
        .annotate(overlaps=Exists(matching_target))
        .aggregate(
            source_count=Count("id", filter=is_source),
            target_count=Count("id", filter=Q(tag_id=target.id)),
            overlap_count=Count("id", filter=is_source & Q(overlaps=True)),
        )
    )
    return TagMergePreview(
        source_count=counts["source_count"],
        target_count=counts["target_count"],
        overlap_count=counts["overlap_count"],
        result_count=counts["source_count"] + counts["target_count"] - counts["overlap_count"],
        tag=target,
    )


def get_merge_preview(team_id: int, source_id: UUID, target_id: UUID) -> TagMergePreview:
    _validate_distinct_tags(source_id, target_id)
    tags = _get_tags(team_id, [source_id, target_id])
    return _get_preview(tags[source_id], tags[target_id])


def _log_mutation(
    tag: Tag, actor: User, activity: str, context: TagManagementContext, changes: list[Change], *, using: str
) -> None:
    log_activity(
        organization_id=tag.team.organization_id,
        team_id=tag.team_id,
        user=actor,
        item_id=context.source_id,
        scope="Tag",
        activity=activity,
        was_impersonated=get_was_impersonated(),
        detail=Detail(name=context.source_name, changes=changes, context=context),
        using=using,
        strict=True,
    )


def _log_assignment_activity(
    before: TaggedItem | None, after: TaggedItem | None, actor: User, log_entries: list[LogActivityEntry]
) -> None:
    model_activity_signal.send(
        sender=TaggedItem,
        scope="TaggedItem",
        before_update=before,
        after_update=after,
        activity="created" if before is None else "deleted" if after is None else "updated",
        user=actor,
        was_impersonated=get_was_impersonated(),
        log_entries=log_entries,
    )


def merge_tags(team_id: int, source_id: UUID, target_id: UUID, actor: User) -> TagMergeResult:
    _validate_distinct_tags(source_id, target_id)
    using = router.db_for_write(Tag)
    source = _get_tags(team_id, [source_id, target_id], using=using)[source_id]
    _validate_sync_assignment_count(source, using=using)
    with tag_assignment_transaction([team_id]) as using, ActingUserContext(actor), defer_activity_log_events():
        tags = _get_tags(team_id, [source_id, target_id], using=using, lock=True)
        source, target = tags[source_id], tags[target_id]
        _validate_sync_assignment_count(source, using=using)
        preview = _get_preview(source, target, using=using)
        items = TaggedItem.objects.using(using)
        matching_target = items.filter(
            team_id=source.team_id, tag_id=target_id, content_type_id=OuterRef("content_type_id")
        ).filter(Q(object_id=OuterRef("object_id")) | Q(object_uuid=OuterRef("object_uuid")))
        source_items = (
            items.filter(team_id=source.team_id, tag_id=source_id)
            .annotate(overlaps=Exists(matching_target))
            .select_related("tag__team")
            .prefetch_related("integer_object", "uuid_object")
        )
        for batch in batched(source_items.iterator(chunk_size=500), 500, strict=False):
            new_items: list[TaggedItem] = []
            log_entries: list[LogActivityEntry] = []
            for item in batch:
                if not item.overlaps:
                    target_item = copy(item)
                    target_item.id = uuid4()
                    target_item.tag = target
                    new_items.append(target_item)
                    _log_assignment_activity(None, target_item, actor, log_entries)
                _log_assignment_activity(item, None, actor, log_entries)
            items.bulk_create(new_items)
            models.QuerySet.delete(items.filter(id__in=[item.id for item in batch]))
            bulk_log_activity(log_entries, using=using, strict=True)
        source.delete(using=using)
        moved_count = preview.source_count - preview.overlap_count
        _log_mutation(
            target,
            actor,
            "merged",
            TagManagementContext(
                operation="merge",
                source_id=str(source_id),
                source_name=source.name,
                target_id=str(target_id),
                target_name=target.name,
                moved_count=moved_count,
                overlap_count=preview.overlap_count,
                usage_count=preview.result_count,
            ),
            [Change(type="Tag", action="changed", field="assignments", before=str(source_id), after=str(target_id))],
            using=using,
        )
        return TagMergeResult(
            moved_count=moved_count, overlap_count=preview.overlap_count, usage_count=preview.result_count, tag=target
        )


def rename_tag(team_id: int, tag_id: UUID, name: str, actor: User) -> Tag:
    name = tagify(name)
    if not name or len(name) > 255 or name.startswith("project-group:"):
        raise ValidationError("Use a tag name between 1 and 255 characters without the project-group: prefix.")
    using = router.db_for_write(Tag)
    tag = _get_tags(team_id, [tag_id], using=using)[tag_id]
    if tag.name != name:
        _validate_sync_assignment_count(tag, using=using)
    try:
        with tag_assignment_transaction([team_id]) as using, ActingUserContext(actor), defer_activity_log_events():
            tag = _get_tags(team_id, [tag_id], using=using, lock=True)[tag_id]
            if tag.name == name:
                return tag
            _validate_sync_assignment_count(tag, using=using)
            tags = Tag.objects.using(using).filter(team_id=team_id)
            if tags.filter(name=name).exists():
                raise ValidationError("A tag with this name already exists. Merge into it instead.")
            previous_tag = copy(tag)
            tags.filter(id=tag_id).update(name=name)
            tag.name = name
            items = (
                TaggedItem.objects.using(using)
                .filter(team_id=tag.team_id, tag_id=tag_id)
                .select_related("tag__team")
                .prefetch_related("integer_object", "uuid_object")
            )
            usage_count = 0
            for batch in batched(items.iterator(chunk_size=500), 500, strict=False):
                log_entries: list[LogActivityEntry] = []
                for item in batch:
                    previous_item = copy(item)
                    previous_item.tag = previous_tag
                    item.tag = tag
                    _log_assignment_activity(previous_item, item, actor, log_entries)
                bulk_log_activity(log_entries, using=using, strict=True)
                usage_count += len(batch)
            _log_mutation(
                tag,
                actor,
                "updated",
                TagManagementContext(
                    operation="rename",
                    source_id=str(tag_id),
                    source_name=previous_tag.name,
                    target_id=str(tag_id),
                    target_name=name,
                    usage_count=usage_count,
                ),
                [Change(type="Tag", action="changed", field="name", before=previous_tag.name, after=name)],
                using=using,
            )
            return tag
    except IntegrityError as error:
        raise ValidationError("A tag with this name already exists. Merge into it instead.") from error


def delete_unused_tags(team_id: int, tag_ids: Collection[UUID]) -> list[UUID]:
    if not tag_ids:
        return []
    with tag_assignment_transaction([team_id]) as using:
        tags = list(
            Tag.objects.using(using)
            .filter(team_id=team_id, id__in=tag_ids)
            .order_by("id")
            .select_for_update(of=("self",))
        )
        # Recheck after acquiring the locks because a waiting statement can have a stale snapshot.
        unused = (
            Tag.objects.using(using)
            .filter(team_id=team_id, id__in=[tag.id for tag in tags])
            .exclude(tagged_items__isnull=False)
        )
        deleted = list(unused.order_by("id").values_list("id", flat=True))
        Tag.objects.using(using).filter(team_id=team_id, id__in=deleted).delete()
        return deleted


def delete_unused_tag(team_id: int, tag_id: UUID, actor: User) -> None:
    with tag_assignment_transaction([team_id]) as using, defer_activity_log_events():
        tag = _get_tags(team_id, [tag_id], using=using, lock=True)[tag_id]
        if TaggedItem.objects.using(using).filter(tag_id=tag_id).exists():
            raise ValidationError("This tag is in use. Merge it into another tag instead.")
        context = TagManagementContext(operation="delete", source_id=str(tag_id), source_name=tag.name)
        tag.delete(using=using)
        _log_mutation(tag, actor, "deleted", context, [], using=using)
