from collections.abc import Sequence
from typing import Any, cast

from django.db import models
from django.db.models import Prefetch, Q, QuerySet, prefetch_related_objects

from drf_spectacular.utils import extend_schema
from rest_framework import response, serializers, status, viewsets
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models import Tag, TaggedItem
from posthog.models.tag import tagify
from posthog.rbac.user_access_control import access_level_satisfied_for_resource


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


def apply_bulk_tag_changes(objects: Sequence, tag_action: str, tags: list[str]) -> list[dict[str, Any]]:
    """Apply an add/remove/set tag mutation to each object and return a per-object result.

    Callers are responsible for team-scoping and access-checking ``objects`` first. When a
    ``prefetched_tags`` attribute is present it is used to avoid a per-object tag query.
    Orphaned tags are cleaned up once at the end.
    """
    normalized_tags = {tagify(t) for t in tags}
    updated: list[dict[str, Any]] = []
    team_id = None

    for obj in objects:
        team_id = obj.team_id
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

    if team_id is not None:
        cleanup_orphan_tags(team_id)

    return updated


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

        updated = apply_bulk_tag_changes(editable_objects, tag_action, tags)
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
