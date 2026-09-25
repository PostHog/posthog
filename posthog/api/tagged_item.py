import dataclasses
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any, Optional, cast
from uuid import UUID

from django.db import models, transaction
from django.db.models import Exists, OuterRef, Prefetch, Q, QuerySet, prefetch_related_objects

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, OpenApiTypes, extend_schema
from rest_framework import pagination, response, serializers, status, viewsets
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.dataclasses import frozen
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Tag, TaggedItem
from posthog.models.activity_logging.activity_log import (
    Change,
    Detail,
    LogActivityEntry,
    bulk_log_activity,
    log_activity,
)
from posthog.models.tag import tagify
from posthog.models.tagged_item_registry import taggable_for_content_type_id

from products.access_control.backend.facade.user_access_control import access_level_satisfied_for_resource

if TYPE_CHECKING:
    from posthog.models.user import User


def set_tags_on_object(tags: list[str], obj: Any) -> list[TaggedItem]:
    """Set tags on a taggable object, creating/deleting TaggedItems as needed.

    This is the core tag-setting logic extracted for reuse across serializers
    and bulk operations.
    """
    deduped_tags = list({tagify(t) for t in tags})
    tagged_item_objects = []

    for tag in deduped_tags:
        tag_instance, _ = Tag.objects.get_or_create(name=tag, team_id=obj.team_id)
        # The instance, not the id, so TaggedItem.save() reads the team without re-fetching.
        tagged_item_instance, _ = obj.tagged_items.get_or_create(tag=tag_instance)
        tagged_item_objects.append(tagged_item_instance)

    # Delete tags that are missing (use individual deletes to trigger activity logging)
    tagged_items_to_delete = obj.tagged_items.exclude(tag__name__in=deduped_tags)
    for tagged_item in tagged_items_to_delete:
        tagged_item.delete()

    return tagged_item_objects


def cleanup_orphan_tags(team_id: int) -> None:
    """Remove tags that are no longer referenced by any TaggedItem."""
    Tag.objects.filter(Q(team_id=team_id) & Q(tagged_items__isnull=True)).delete()


@frozen
class TagUsage:
    """One tag, and how many objects of each taggable kind carry it."""

    tag: Tag
    counts_by_type: dict[str, int]

    @property
    def total_count(self) -> int:
        return sum(self.counts_by_type.values())


def tag_usages(tags: Sequence[Tag]) -> list[TagUsage]:
    """Count the objects each tag is on, split by the kind of object.

    The split matters because a tag is shared by every taggable model in the team: a
    support agent who renames a ticket tag also renames it on dashboards and insights,
    and the per-kind count is what tells them so.
    """
    counts: dict[UUID, dict[str, int]] = {tag.id: {} for tag in tags}
    rows = (
        TaggedItem.objects.filter(tag_id__in=list(counts))
        .values("tag_id", "content_type_id")
        .annotate(count=models.Count("id"))
    )
    for row in rows:
        entry = taggable_for_content_type_id(row["content_type_id"]) if row["content_type_id"] else None
        if entry is not None:
            counts[row["tag_id"]][entry.legacy_field] = row["count"]
    return [TagUsage(tag=tag, counts_by_type=counts[tag.id]) for tag in tags]


def rename_tag(tag: Tag, name: str) -> Tag:
    """Rename a tag in place, so every object that carries it follows.

    ``Tag.save`` sends the model activity signal, so this leaves one activity-log entry
    for the rename, not one per tagged object.
    """
    tag.name = name
    tag.save()
    return tag


def delete_tag(tag: Tag) -> int:
    """Remove a tag from every object that carries it, and return how many it was on.

    The ``TaggedItem`` rows go through a queryset delete rather than ``Model.delete``, so
    a tag on thousands of tickets does not write thousands of activity-log entries.
    """
    with transaction.atomic():
        items = TaggedItem.objects.filter(tag=tag)
        removed = items.count()
        items.delete()
        tag.delete()
    return removed


def merge_tags(source: Tag, target: Tag) -> int:
    """Move every object tagged ``source`` onto ``target``, drop ``source``, return the count moved.

    An object that already carries both tags keeps the row it has, because
    ``(content type, object, tag)`` is unique; its ``source`` row is dropped instead of
    repointed. Both steps are queryset writes, for the same reason as ``delete_tag``.
    """
    duplicate_on_target = TaggedItem.objects.filter(tag=target, content_type=OuterRef("content_type")).filter(
        Q(object_id=OuterRef("object_id")) | Q(object_uuid=OuterRef("object_uuid"))
    )
    with transaction.atomic():
        TaggedItem.objects.filter(tag=source).filter(Exists(duplicate_on_target)).delete()
        moved = TaggedItem.objects.filter(tag=source).update(tag=target)
        source.delete()
    return moved


def normalize_tag_names(tags: Iterable[str]) -> set[str]:
    """The tag names a request's raw strings resolve to, minus the blanks.

    ``tagify`` strips whitespace, so a payload of ``[""]`` or ``["  "]`` would otherwise reach
    ``Tag.objects.get_or_create`` and leave an empty tag that renders as nothing.
    """
    return {name for name in (tagify(tag) for tag in tags) if name}


def current_tag_names(obj: Any) -> set[str]:
    """The object's tags, preferring a ``prefetched_tags`` attribute over a fresh query."""
    tagged_items = obj.prefetched_tags if hasattr(obj, "prefetched_tags") else obj.tagged_items.select_related("tag")
    return {tagged_item.tag.name for tagged_item in tagged_items}


def resolve_bulk_tags(current_tags: set[str], tag_action: str, normalized_tags: set[str]) -> set[str]:
    """The tags an object ends up with after an add/remove/set bulk mutation."""
    if tag_action == "add":
        return current_tags | normalized_tags
    if tag_action == "remove":
        return current_tags - normalized_tags
    return set(normalized_tags)


@dataclasses.dataclass(frozen=True)
class BulkTagActivityContext:
    """Context needed to write an activity-log entry for each object mutated in bulk.

    ``scope`` is the resource's ``ActivityScope`` (e.g. ``"FeatureFlag"``) and ``activity`` is the
    verb its single-object update path uses ("updated" for flags/insights/dashboards, "changed" for
    event definitions), so a bulk entry matches what that path already writes. Passing this to
    ``apply_bulk_tag_changes`` makes the bulk path leave the same audit trail; omitting it preserves
    the old silent behavior.
    """

    scope: str
    user: "User"
    was_impersonated: bool
    activity: str


def apply_bulk_tag_changes(
    objects: Sequence,
    tag_action: str,
    tags: list[str],
    *,
    activity_context: Optional[BulkTagActivityContext] = None,
) -> list[dict[str, Any]]:
    """Apply an add/remove/set tag mutation to each object and return a per-object result.

    Callers are responsible for team-scoping and access-checking ``objects`` first. When a
    ``prefetched_tags`` attribute is present it is used to avoid a per-object tag query.
    Orphaned tags are cleaned up per affected team, since ``objects`` may span multiple teams
    when the caller scopes by project (e.g. event definitions across environments).

    When ``activity_context`` is provided, an activity-log entry carrying a ``tags`` diff is
    recorded for every object whose tags actually change, mirroring the single-object update path
    so the bulk endpoint leaves the same audit trail.
    """
    normalized_tags = normalize_tag_names(tags)
    updated: list[dict[str, Any]] = []
    team_ids: set[int] = set()
    activity_entries: list[LogActivityEntry] = []

    for obj in objects:
        team_ids.add(obj.team_id)
        current_tags = current_tag_names(obj)
        new_tags = resolve_bulk_tags(current_tags, tag_action, normalized_tags)

        set_tags_on_object(list(new_tags), obj)
        updated.append({"id": obj.id, "tags": sorted(new_tags)})

        if activity_context is not None and current_tags != new_tags:
            activity_entries.append(
                _bulk_tag_activity_entry(obj, sorted(current_tags), sorted(new_tags), activity_context)
            )

    for team_id in team_ids:
        cleanup_orphan_tags(team_id)

    if activity_entries:
        bulk_log_activity(activity_entries)

    return updated


def _bulk_tag_activity_entry(
    obj: Any, before: list[str], after: list[str], context: BulkTagActivityContext
) -> LogActivityEntry:
    """Build an activity-log entry for a single bulk-tagged object.

    ``organization_id`` is left ``None`` (the team is enough to scope the entry, and ``objects``
    can span teams within a project), matching the single-object update path.
    """
    return LogActivityEntry(
        organization_id=None,
        team_id=obj.team_id,
        user=context.user,
        was_impersonated=context.was_impersonated,
        item_id=str(obj.id),
        scope=context.scope,
        activity=context.activity,
        detail=Detail(
            name=getattr(obj, "name", None) or getattr(obj, "key", None),
            # short_id is how insights are linked in the activity feed; None (and ignored) elsewhere.
            short_id=getattr(obj, "short_id", None),
            changes=[Change(type=context.scope, action="changed", field="tags", before=before, after=after)],
        ),
    )


class TaggedItemSerializerMixin(serializers.Serializer):
    """
    Serializer mixin that handles tags for objects.
    """

    tags = serializers.ListField(required=False)

    def _attempt_set_tags(self, tags, obj):
        if not obj or tags is None:
            # If the object hasn't been created yet, this method will be called again on the create method.
            return

        obj.prefetched_tags = set_tags_on_object(tags, obj)
        cleanup_orphan_tags(obj.team_id)

    def to_representation(self, obj):
        ret = super().to_representation(obj)
        if hasattr(obj, "prefetched_tags"):
            ret["tags"] = [p.tag.name for p in obj.prefetched_tags]
        elif obj.pk:
            ret["tags"] = list(obj.tagged_items.values_list("tag__name", flat=True)) if obj.tagged_items else []
        else:
            ret["tags"] = []
        return ret

    def create(self, validated_data):
        validated_data.pop("tags", None)
        instance = super().create(validated_data)
        self._attempt_set_tags(self.initial_data.get("tags"), instance)
        return instance

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        self._attempt_set_tags(self.initial_data.get("tags"), instance)
        return instance


BULK_UPDATE_TAGS_MAX_IDS = 500
BULK_UPDATE_TAGS_MAX_TAGS = 100
TAG_NAME_MAX_LENGTH = 255  # Mirrors Tag.name's max_length
# One reason for both missing and inaccessible objects, so callers can't probe which
# restricted IDs exist by comparing skipped reasons.
BULK_UPDATE_TAGS_SKIPPED_REASON = "Not found or no edit access"
# Tags are written with a get_or_create per (object, tag), so ids × distinct tags is the unit of
# database work a single request can demand; bound the product, not just each list, or 500 ids
# with 100 tags each still turns one request into 50k writes.
BULK_UPDATE_TAGS_MAX_OPERATIONS = 10_000
# Tag lists are small next to the objects they tag, and the settings list reads the whole page at once.
TAG_USAGE_PAGE_SIZE = 500


class BulkUpdateTagsAction(models.TextChoices):
    ADD = "add", "add"
    REMOVE = "remove", "remove"
    SET = "set", "set"


class BulkUpdateTagsRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
        max_length=BULK_UPDATE_TAGS_MAX_IDS,
        help_text="List of object IDs to update tags on.",
    )
    action = serializers.ChoiceField(
        choices=BulkUpdateTagsAction.choices,
        help_text="'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(max_length=TAG_NAME_MAX_LENGTH),
        max_length=BULK_UPDATE_TAGS_MAX_TAGS,
        help_text="Tag names to add, remove, or set (up to 100 per request, 255 characters each).",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["action"] in ("add", "remove") and not attrs.get("tags"):
            raise serializers.ValidationError({"tags": f"tags must not be empty for action '{attrs['action']}'."})
        distinct_tags = {tagify(tag) for tag in attrs.get("tags", [])}
        if len(attrs["ids"]) * len(distinct_tags) > BULK_UPDATE_TAGS_MAX_OPERATIONS:
            raise serializers.ValidationError(
                {
                    "tags": f"Too many changes in one request: ids × distinct tags must not exceed {BULK_UPDATE_TAGS_MAX_OPERATIONS}."
                }
            )
        return attrs


class BulkUpdateTagsItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    tags = serializers.ListField(child=serializers.CharField())


class BulkUpdateTagsErrorSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    reason = serializers.CharField()


class BulkUpdateTagsResponseSerializer(serializers.Serializer):
    updated = BulkUpdateTagsItemSerializer(many=True)
    skipped = BulkUpdateTagsErrorSerializer(many=True)


class BulkUpdateTagsUUIDRequestSerializer(BulkUpdateTagsRequestSerializer):
    """Variant of ``BulkUpdateTagsRequestSerializer`` for resources keyed by UUID (e.g. event definitions)."""

    ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        max_length=BULK_UPDATE_TAGS_MAX_IDS,
        help_text="List of object UUIDs to update tags on.",
    )


class BulkUpdateTagsUUIDItemSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="UUID of the object whose tags were updated.")
    tags = serializers.ListField(
        child=serializers.CharField(),
        help_text="The object's full tag list after the update.",
    )


class BulkUpdateTagsUUIDErrorSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="UUID of the object that was skipped.")
    reason = serializers.CharField(help_text="Why the object was skipped, e.g. 'Not found or no edit access'.")


class BulkUpdateTagsUUIDResponseSerializer(serializers.Serializer):
    updated = BulkUpdateTagsUUIDItemSerializer(many=True, help_text="Objects whose tags were successfully updated.")
    skipped = BulkUpdateTagsUUIDErrorSerializer(many=True, help_text="Objects that were skipped, with a reason each.")


def _prefetch_tags_for_instances(instances: Sequence) -> None:
    """Manually prefetch tagged_items for a list of model instances.

    Handles RawQuerySet results that may have NULL PKs (e.g., from FULL OUTER JOINs)
    by only prefetching for instances with valid PKs and setting empty tags on the rest.
    Django 5 raises ValueError when unsaved instances are passed to related filters.
    """
    valid_instances = [obj for obj in instances if obj.pk is not None]
    null_pk_instances = [obj for obj in instances if obj.pk is None]

    if valid_instances:
        prefetch_related_objects(
            valid_instances,
            Prefetch(
                "tagged_items",
                queryset=TaggedItem.objects.select_related("tag"),
                to_attr="prefetched_tags",
            ),
        )

    for obj in null_pk_instances:
        obj.prefetched_tags = []


class TaggedItemViewSetMixin(viewsets.GenericViewSet):
    # Set to the resource's ActivityScope (e.g. "FeatureFlag") to record an activity-log entry per
    # object whose tags change via ``bulk_update_tags``. Left ``None`` for resources that don't log
    # bulk tag edits, which leaves their behavior unchanged.
    bulk_tag_activity_scope: Optional[str] = None

    # Request serializer for ``bulk_update_tags``. UUID-PK resources set the UUID variant and must
    # also override the action's OpenAPI schema via ``@extend_schema_view`` on the viewset class.
    bulk_update_tags_request_serializer_class: type[BulkUpdateTagsRequestSerializer] = BulkUpdateTagsRequestSerializer

    def _bulk_tag_activity_context(self) -> Optional[BulkTagActivityContext]:
        if not self.bulk_tag_activity_scope:
            return None
        return BulkTagActivityContext(
            scope=self.bulk_tag_activity_scope,
            user=cast("User", self.request.user),
            was_impersonated=is_impersonated(self.request),
            # Flags, insights, and dashboards log single-object updates under the "updated" verb.
            activity="updated",
        )

    def validate_bulk_tag_changes(self, objects: Sequence, tag_action: str, tags: list[str]) -> None:
        """Hook for resources whose tags carry a rule the bulk path must honor.

        Raise ``serializers.ValidationError`` to reject the whole request. Rejecting beats skipping
        here: the bulk-tag form reports skipped objects as permission failures, so a rule-based skip
        would reach the user as the wrong reason.

        A viewset that reimplements ``bulk_update_tags`` must call this itself before
        ``apply_bulk_tag_changes``, or its resource silently opts out of its own rule.
        """

    def prefetch_tagged_items_if_available(self, queryset: QuerySet | models.query.RawQuerySet) -> QuerySet:
        if isinstance(queryset, models.query.RawQuerySet):
            return queryset  # type: ignore[return-value]  # ty: ignore[invalid-return-type]
        return queryset.prefetch_related(
            Prefetch(
                "tagged_items",
                queryset=TaggedItem.objects.select_related("tag"),
                to_attr="prefetched_tags",
            )
        )

    def filter_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = super().filter_queryset(queryset)
        return self.prefetch_tagged_items_if_available(queryset)

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        if page is not None and isinstance(queryset, models.query.RawQuerySet):
            _prefetch_tags_for_instances(page)
        return page

    @extend_schema(
        request=BulkUpdateTagsRequestSerializer,
        responses={200: BulkUpdateTagsResponseSerializer},
    )
    @action(methods=["POST"], detail=False)
    def bulk_update_tags(self, request, **kwargs):
        """
        Bulk update tags on multiple objects.

        PAT access: this action has no ``required_scopes=`` on the decorator —
        inheriting viewsets must add ``"bulk_update_tags"`` to their
        ``scope_object_write_actions`` list to accept personal API keys.
        Without that opt-in, ``APIScopePermission`` rejects PAT requests with
        "This action does not support personal API key access". Done per-viewset
        so granting ``<scope>:write`` for one resource doesn't leak access to
        sibling resources that share this mixin.

        Accepts:
        - {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}

        Actions:
        - "add": Add tags to existing tags on each object
        - "remove": Remove specific tags from each object
        - "set": Replace all tags on each object with the provided list
        """
        serializer = self.bulk_update_tags_request_serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        validated_ids: list[int | UUID] = validated["ids"]
        tag_action: str = validated["action"]
        tags: list[str] = validated["tags"]

        # Build queryset from the viewset's own queryset (inherits team/project scoping)
        queryset = self.get_queryset().filter(id__in=validated_ids)
        queryset = self.prefetch_tagged_items_if_available(queryset)
        objects = list(queryset)

        # Access control: filter to only objects the user can edit
        scope_object = getattr(self, "scope_object", None)
        user_access_control = getattr(self, "user_access_control", None)

        editable_objects = []
        errors: list[dict[str, Any]] = []

        if not user_access_control or not scope_object:
            return response.Response(
                {"detail": "Bulk tag updates are not supported for this resource."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_access_control.preload_object_access_controls(cast(list, objects))
        for obj in objects:
            user_access_level = user_access_control.get_user_access_level(obj)
            if user_access_level and access_level_satisfied_for_resource(scope_object, user_access_level, "editor"):
                editable_objects.append(obj)
            else:
                errors.append({"id": obj.id, "reason": BULK_UPDATE_TAGS_SKIPPED_REASON})

        # Track missing IDs
        found_ids = {obj.id for obj in objects}
        for obj_id in validated_ids:
            if obj_id not in found_ids:
                errors.append({"id": obj_id, "reason": BULK_UPDATE_TAGS_SKIPPED_REASON})

        self.validate_bulk_tag_changes(editable_objects, tag_action, tags)

        updated = apply_bulk_tag_changes(
            editable_objects, tag_action, tags, activity_context=self._bulk_tag_activity_context()
        )
        return response.Response({"updated": updated, "skipped": errors})


class TaggedItemSerializer(serializers.Serializer):
    tag = serializers.SerializerMethodField()

    def get_tag(self, obj: TaggedItem) -> str:
        return obj.tag.name


class TagUsageSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="tag.id", help_text="Unique identifier of the tag.")
    name = serializers.CharField(source="tag.name", help_text="The tag's name, always lowercase and trimmed.")
    counts_by_type = serializers.DictField(
        child=serializers.IntegerField(),
        help_text=(
            "How many objects of each kind carry this tag, keyed by object kind "
            "(for example 'ticket', 'dashboard', 'insight'). Kinds with no objects are omitted."
        ),
    )
    total_count = serializers.IntegerField(help_text="How many objects carry this tag in total, across all kinds.")


class TagRenameRequestSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=TAG_NAME_MAX_LENGTH,
        help_text="The tag's new name. It is trimmed and lowercased, and must not match another tag in the project.",
    )


class TagMergeRequestSerializer(serializers.Serializer):
    into_id = serializers.UUIDField(
        help_text="Unique identifier of the tag to keep. Every object tagged with this tag moves onto it."
    )


class TagMergeResponseSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Unique identifier of the tag that was kept.")
    name = serializers.CharField(help_text="Name of the tag that was kept.")
    moved_count = serializers.IntegerField(
        help_text="How many objects moved onto the kept tag. Objects that already carried both tags are not counted."
    )


class TagErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the request was rejected.")


@extend_schema(extensions={"x-product": "core"})
class TaggedItemViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = TaggedItemSerializer
    queryset = Tag.objects.all()

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team=self.team)

    @extend_schema(
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, required=False),
            OpenApiParameter("limit", OpenApiTypes.INT, required=False),
            OpenApiParameter("offset", OpenApiTypes.INT, required=False),
        ]
    )
    def list(self, request, *args, **kwargs) -> response.Response:
        tags = Tag.objects.filter(team=self.team).values_list("name", flat=True).distinct().order_by("name")
        search = request.query_params.get("search")

        if search is None:
            return response.Response(tags)

        if search:
            tags = tags.filter(name__icontains=search)

        paginator = pagination.LimitOffsetPagination()
        paginator.default_limit = 100
        paginator.max_limit = 100
        page = paginator.paginate_queryset(tags, request, view=self)
        return paginator.get_paginated_response(page)

    @extend_schema(
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, required=False),
            OpenApiParameter("limit", OpenApiTypes.INT, required=False),
            OpenApiParameter("offset", OpenApiTypes.INT, required=False),
        ],
        responses=TagUsageSerializer(many=True),
    )
    @action(methods=["GET"], detail=False)
    def usage(self, request, *args, **kwargs) -> response.Response:
        """List the project's tags with the number of objects each one is on, by object kind."""
        tags = self.get_queryset().order_by("name")
        search = request.query_params.get("search")
        if search:
            tags = tags.filter(name__icontains=search)

        paginator = pagination.LimitOffsetPagination()
        paginator.default_limit = TAG_USAGE_PAGE_SIZE
        paginator.max_limit = TAG_USAGE_PAGE_SIZE
        page = paginator.paginate_queryset(tags, request, view=self)
        return paginator.get_paginated_response(TagUsageSerializer(tag_usages(page or []), many=True).data)

    @extend_schema(
        request=TagRenameRequestSerializer,
        responses={
            200: TagUsageSerializer,
            400: OpenApiResponse(response=TagErrorSerializer, description="The name is blank or already taken."),
        },
    )
    def partial_update(self, request, *args, **kwargs) -> response.Response:
        """Rename a tag on every object that carries it."""
        tag = self.get_object()
        serializer = TagRenameRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        name = tagify(serializer.validated_data["name"])
        if not name:
            raise serializers.ValidationError({"name": "Enter a tag name."})
        if name != tag.name and Tag.objects.filter(team=self.team, name=name).exists():
            raise serializers.ValidationError({"name": f"'{name}' already exists. Merge the two tags instead."})

        rename_tag(tag, name)
        return response.Response(TagUsageSerializer(tag_usages([tag])[0]).data)

    @extend_schema(responses={204: None})
    def destroy(self, request, *args, **kwargs) -> response.Response:
        """Remove a tag from every object that carries it."""
        tag = self.get_object()
        # Django blanks the primary key on delete, so the audit entry needs these read first.
        tag_id, tag_name, team_id = tag.id, tag.name, tag.team_id
        removed = delete_tag(tag)
        self._log_tag_activity(tag_id, team_id, "deleted", Detail(name=tag_name, changes=[]))
        return response.Response(status=status.HTTP_204_NO_CONTENT, headers={"X-Objects-Untagged": str(removed)})

    @extend_schema(
        request=TagMergeRequestSerializer,
        responses={
            200: TagMergeResponseSerializer,
            400: OpenApiResponse(response=TagErrorSerializer, description="The target tag is missing or the same tag."),
        },
    )
    @action(methods=["POST"], detail=True)
    def merge(self, request, *args, **kwargs) -> response.Response:
        """Move every object tagged with this tag onto another tag, then drop this one."""
        source = self.get_object()
        serializer = TagMergeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target = self.get_queryset().filter(id=serializer.validated_data["into_id"]).first()
        if target is None:
            raise serializers.ValidationError({"into_id": "Tag not found."})
        if target.id == source.id:
            raise serializers.ValidationError({"into_id": "Pick a different tag to merge into."})

        source_name = source.name
        moved = merge_tags(source, target)
        self._log_tag_activity(
            target.id,
            target.team_id,
            "merged",
            Detail(
                name=target.name,
                changes=[Change(type="Tag", action="merged", field="name", before=source_name, after=target.name)],
            ),
        )
        return response.Response(
            TagMergeResponseSerializer({"id": target.id, "name": target.name, "moved_count": moved}).data
        )

    def _log_tag_activity(self, tag_id: UUID, team_id: int, activity: str, detail: Detail) -> None:
        log_activity(
            organization_id=self.team.organization_id,
            team_id=team_id,
            user=cast("User", self.request.user),
            was_impersonated=is_impersonated(self.request),
            item_id=str(tag_id),
            scope="Tag",
            activity=activity,
            detail=detail,
        )
