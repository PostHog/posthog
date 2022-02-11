from django.db.models import Prefetch
from infi.clickhouse_orm import Q
from rest_framework import serializers, viewsets

from posthog.api.utils import EnterpriseMethodField
from posthog.constants import AvailableFeature
from posthog.models import Tag, TaggedItem


# Noop non-ee
class TagsSerializer(serializers.ListField):
    def to_representation(self, value):
        return []

    def to_internal_value(self, data):
        return


class EnterpriseTagsSerializer(serializers.ListField):
    def __init__(self, **kwargs):
        self.child = serializers.PrimaryKeyRelatedField(queryset=Tag.objects.all())
        super().__init__(**kwargs)

    def to_representation(self, obj):
        if hasattr(obj, "prefetched_tags"):
            return [p.tag.name for p in obj.prefetched_tags]
        return super(EnterpriseTagsSerializer, self).to_representation(obj)

    #
    # def to_internal_value(self, tags):
    #     obj = self.parent.instance
    #     if not obj:
    #         # If the object hasn't been created yet, this method will be called again on the create method.
    #         return
    #
    #     # Clean and dedupe tags
    #     deduped_tags = list(set([t.strip() for t in tags]))
    #     tagged_item_objects = []
    #
    #     # Create tags
    #     for tag in deduped_tags:
    #         tag_instance, _ = Tag.objects.get_or_create(name=tag, team_id=obj.team_id)
    #         tagged_item_instance, _ = obj.tags.get_or_create(tag_id=tag_instance.id)
    #         tagged_item_objects.append(tagged_item_instance)
    #
    #     # Delete tags that are missing
    #     obj.tags.exclude(tag__name__in=deduped_tags).delete()
    #
    #     # Cleanup tags that aren't used by team
    #     Tag.objects.filter(Q(team_id=obj.team_id) & Q(taggeditems__isnull=True)).delete()
    #
    #     obj.prefetched_tags = tagged_item_objects


class TaggedItemSerializerMixin(serializers.Serializer):
    """
    Serializer mixin that resolves appropriate response for tags depending on license.
    """

    # tags = EnterpriseMethodField(
    #     serializer=TagsSerializer,
    #     ee_serializer=EnterpriseTagsSerializer,
    #     available_feature=AvailableFeature.TAGGING,
    #     required=False
    # )

    def _is_licensed(self):
        return (
            "request" in self.context
            and not self.context["request"].user.is_anonymous
            and self.context["request"].user.organization.is_feature_available(AvailableFeature.TAGGING)
        )

    def _set_tags(self, tags, obj):
        if not obj:
            # If the object hasn't been created yet, this method will be called again on the create method.
            return

        # Normalize and dedupe tags
        deduped_tags = list(set([t.strip().lower() for t in tags]))
        tagged_item_objects = []

        # Create tags
        for tag in deduped_tags:
            tag_instance, _ = Tag.objects.get_or_create(name=tag, team_id=obj.team_id)
            tagged_item_instance, _ = obj.tagged_items.get_or_create(tag_id=tag_instance.id)
            tagged_item_objects.append(tagged_item_instance)

        # Delete tags that are missing
        obj.tags.exclude(tag__name__in=deduped_tags).delete()

        # Cleanup tags that aren't used by team
        Tag.objects.filter(Q(team_id=obj.team_id) & Q(tagged_items__isnull=True)).delete()

        obj.prefetched_tags = tagged_item_objects

    def to_representation(self, obj):
        ret = super(TaggedItemSerializerMixin, self).to_representation(obj)
        ret["tags"] = []
        if self._is_licensed():
            if hasattr(obj, "prefetched_tags"):
                ret["tags"] = [p.tag.name for p in obj.prefetched_tags]
            else:
                ret["tags"] = list(obj.tagged_items.values_list("tag__name", flat=True)) if obj.tags else []
        return ret

    def create(self, validated_data):
        instance = super(TaggedItemSerializerMixin, self).create(validated_data)

        if self._is_licensed() and self.initial_data.get("tags", None):
            self._set_tags(self.initial_data["tags"], instance)

        return instance

    def update(self, validated_data):
        instance = super(TaggedItemSerializerMixin, self).update(validated_data)

        if self._is_licensed() and self.initial_data.get("tags", None):
            self._set_tags(self.initial_data["tags"], instance)

        return instance


class TaggedItemViewSetMixin(viewsets.GenericViewSet):
    def is_licensed(self):
        return (
            not self.request.user.is_anonymous
            # The below triggers an extra query to resolve user's organization.
            and self.request.user.organization.is_feature_available(AvailableFeature.TAGGING)  # type: ignore
        )

    def get_queryset(self):
        queryset = super(TaggedItemViewSetMixin, self).get_queryset()
        if self.is_licensed():
            return queryset.prefetch_related(
                Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags")
            )
        return queryset.defer("tagged_items")
