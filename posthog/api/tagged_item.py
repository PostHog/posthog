import dataclasses
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Optional, cast

from django.db import models
from django.db.models import Prefetch, Q, QuerySet, prefetch_related_objects

from drf_spectacular.utils import extend_schema
from rest_framework import response, serializers, status, viewsets
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Tag, TaggedItem
from posthog.models.activity_logging.activity_log import Change, Detail, LogActivityEntry, bulk_log_activity
from posthog.models.tag import tagify
from posthog.rbac.user_access_control import access_level_satisfied_for_resource

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
        tagged_item_instance, _ = obj.tagged_items.get_or_create(tag_id=tag_instance.id)
        tagged_item_objects.append(tagged_item_instance)

    # Delete tags that are missing (use individual deletes to trigger activity logging)
    tagged_items_to_delete = obj.tagged_items.exclude(tag__name__in=deduped_tags)
    for tagged_item in tagged_items_to_delete:
        tagged_item.delete()

    return tagged_item_objects


def cleanup_orphan_tags(team_id: int) -> None:
    """Remove tags that are no longer referenced by any TaggedItem."""
    Tag.objects.filter(Q(team_id=team_id) & Q(tagged_items__isnull=True)).delete()


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
    normalized_tags = {tagify(t) for t in tags}
    updated: list[dict[str, Any]] = []
    team_ids: set[int] = set()
    activity_entries: list[LogActivityEntry] = []

    for obj in objects:
        team_ids.add(obj.team_id)
        current_tags = {
            ti.tag.name
            for ti in (
                obj.prefetched_tags if hasattr(obj, "prefetched_tags") else obj.tagged_items.select_related("tag").all()
            )
        }

        if tag_action == "add":
            new_tags = current_tags | normalized_tags
        elif tag_action == "remove":
            new_tags = current_tags - normalized_tags
        else:  # set
            new_tags = set(normalized_tags)

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


class BulkUpdateTagsRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
        max_length=BULK_UPDATE_TAGS_MAX_IDS,
        help_text="List of object IDs to update tags on.",
    )
    action = serializers.ChoiceField(
        choices=["add", "remove", "set"],
        help_text="'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        help_text="Tag names to add, remove, or set.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["action"] in ("add", "remove") and not attrs.get("tags"):
            raise serializers.ValidationError({"tags": f"tags must not be empty for action '{attrs['action']}'."})
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
    reason = serializers.CharField(help_text="Why the object was skipped, e.g. 'Not found'.")


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
        serializer = BulkUpdateTagsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        validated_ids: list[int] = validated["ids"]
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
                errors.append({"id": obj.id, "reason": "Permission denied"})

        # Track missing IDs
        found_ids = {obj.id for obj in objects}
        for obj_id in validated_ids:
            if obj_id not in found_ids:
                errors.append({"id": obj_id, "reason": "Not found"})

        updated = apply_bulk_tag_changes(
            editable_objects, tag_action, tags, activity_context=self._bulk_tag_activity_context()
        )
        return response.Response({"updated": updated, "skipped": errors})


class TaggedItemSerializer(serializers.Serializer):
    tag = serializers.SerializerMethodField()

    def get_tag(self, obj: TaggedItem) -> str:
        return obj.tag.name


class TaggedItemViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = TaggedItemSerializer
    queryset = Tag.objects.none()

    def list(self, request, *args, **kwargs) -> response.Response:
        return response.Response(
            Tag.objects.filter(team=self.team).values_list("name", flat=True).distinct().order_by("name")
        )
