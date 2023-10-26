from django.db.models import Prefetch, Q, QuerySet
from rest_framework import response, serializers, status, viewsets
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import StructuredViewSetMixin
from posthog.constants import AvailableFeature
from posthog.models import Tag, TaggedItem, User
from posthog.models.tag import tagify


class TaggedItemSerializerMixin(serializers.Serializer):
    """
    Serializer mixin that resolves appropriate response for tags depending on license.
    """

    tags = serializers.ListField(required=False)

    def _is_licensed(self):
        return (
            "request" in self.context
            and not self.context["request"].user.is_anonymous
            and self.context["request"].user.organization.is_feature_available(AvailableFeature.TAGGING)
        )

    def _attempt_set_tags(self, tags, obj, force_create=False):
        if not force_create and not self._is_licensed() and tags is not None:
            # Silently fail on updating tags so that entire request isn't blocked
            return

        if not obj or tags is None:
            # If the object hasn't been created yet, this method will be called again on the create method.
            return

        # Normalize and dedupe tags
        deduped_tags = list({tagify(t) for t in tags})
        tagged_item_objects = []

        # Create tags
        for tag in deduped_tags:
            tag_instance, _ = Tag.objects.get_or_create(name=tag, team_id=obj.team_id)
            tagged_item_instance, _ = obj.tagged_items.get_or_create(tag_id=tag_instance.id)
            tagged_item_objects.append(tagged_item_instance)

        # Delete tags that are missing
        obj.tagged_items.exclude(tag__name__in=deduped_tags).delete()

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
                ret["tags"] = list(obj.tagged_items.values_list("tag__name", flat=True)) if obj.tagged_items else []
        return ret

    def create(self, validated_data):
        validated_data.pop("tags", None)
        instance = super(TaggedItemSerializerMixin, self).create(validated_data)
        self._attempt_set_tags(self.initial_data.get("tags"), instance)
        return instance

    def update(self, instance, validated_data):
        instance = super(TaggedItemSerializerMixin, self).update(instance, validated_data)
        self._attempt_set_tags(self.initial_data.get("tags"), instance)
        return instance


def is_licensed_for_tagged_items(user: User) -> bool:
    return (
        not user.is_anonymous
        # The below triggers an extra query to resolve user's organization.
        and user.organization is not None
        and user.organization.is_feature_available(AvailableFeature.TAGGING)
    )


class TaggedItemViewSetMixin(viewsets.GenericViewSet):
    def is_licensed(self):
        return is_licensed_for_tagged_items(self.request.user)  # type: ignore

    def prefetch_tagged_items_if_available(self, queryset: QuerySet) -> QuerySet:
        if self.is_licensed():
            return queryset.prefetch_related(
                Prefetch(
                    "tagged_items",
                    queryset=TaggedItem.objects.select_related("tag"),
                    to_attr="prefetched_tags",
                )
            )
        return queryset

    def get_queryset(self):
        queryset = super(TaggedItemViewSetMixin, self).get_queryset()
        return self.prefetch_tagged_items_if_available(queryset)


class TaggedItemSerializer(serializers.Serializer):
    tag = serializers.SerializerMethodField()

    def get_tag(self, obj: TaggedItem) -> str:
        return obj.tag.name


class TaggedItemViewSet(StructuredViewSetMixin, GenericViewSet):
    serializer_class = TaggedItemSerializer
    queryset = Tag.objects.none()

    def list(self, request, *args, **kwargs) -> response.Response:
        if not is_licensed_for_tagged_items(self.request.user):  # type: ignore
            return response.Response([], status=status.HTTP_402_PAYMENT_REQUIRED)

        return response.Response(Tag.objects.filter(team=self.team).values_list("name", flat=True).distinct())
