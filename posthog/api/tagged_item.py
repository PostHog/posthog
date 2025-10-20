import dataclasses
from typing import Optional

from django.db.models import Prefetch, Q, QuerySet
from django.dispatch import receiver

from rest_framework import response, serializers, status, viewsets
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.constants import AvailableFeature
from posthog.models import Tag, TaggedItem, User
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.activity_logging.tag_utils import get_tagged_item_related_object_info
from posthog.models.signals import model_activity_signal
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

        # Delete tags that are missing (use individual deletes to trigger activity logging)
        tagged_items_to_delete = obj.tagged_items.exclude(tag__name__in=deduped_tags)
        for tagged_item in tagged_items_to_delete:
            tagged_item.delete()

        # Cleanup tags that aren't used by team (exclude tags that are default evaluation tags (have team_defaults relationship))
        Tag.objects.filter(
            Q(team_id=obj.team_id) & Q(tagged_items__isnull=True) & Q(team_defaults__isnull=True)
        ).delete()

        obj.prefetched_tags = tagged_item_objects

    def to_representation(self, obj):
        ret = super().to_representation(obj)
        ret["tags"] = []
        if self._is_licensed():
            if hasattr(obj, "prefetched_tags"):
                ret["tags"] = [p.tag.name for p in obj.prefetched_tags]
            else:
                ret["tags"] = list(obj.tagged_items.values_list("tag__name", flat=True)) if obj.tagged_items else []
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
        if not self.is_licensed():
            return queryset

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


class TaggedItemSerializer(serializers.Serializer):
    tag = serializers.SerializerMethodField()

    def get_tag(self, obj: TaggedItem) -> str:
        return obj.tag.name


class TaggedItemViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = TaggedItemSerializer
    queryset = Tag.objects.none()

    def list(self, request, *args, **kwargs) -> response.Response:
        if not is_licensed_for_tagged_items(self.request.user):  # type: ignore
            return response.Response([], status=status.HTTP_402_PAYMENT_REQUIRED)

        return response.Response(Tag.objects.filter(team=self.team).values_list("name", flat=True).distinct())


@dataclasses.dataclass(frozen=True)
class TagContext(ActivityContextBase):
    team_id: int
    name: str


@dataclasses.dataclass(frozen=True)
class TaggedItemContext(ActivityContextBase):
    tag_name: str
    tag_id: str
    team_id: int
    related_object_type: Optional[str] = None
    related_object_id: Optional[str] = None
    related_object_name: Optional[str] = None


@receiver(model_activity_signal, sender=Tag)
def handle_tag_change(sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs):
    context = TagContext(
        team_id=after_update.team_id,
        name=after_update.name,
    )

    log_activity(
        organization_id=after_update.team.organization_id if after_update.team else None,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=after_update.name,
            context=context,
        ),
    )


@receiver(model_activity_signal, sender=TaggedItem)
def handle_tagged_item_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    # Use after_update for create/update, before_update for delete
    tagged_item = after_update or before_update

    if tagged_item and tagged_item.tag:
        related_object_type, related_object_id, related_object_name = get_tagged_item_related_object_info(tagged_item)

        context = TaggedItemContext(
            tag_name=tagged_item.tag.name,
            tag_id=str(tagged_item.tag.id),
            team_id=tagged_item.tag.team_id,
            related_object_type=related_object_type,
            related_object_id=related_object_id,
            related_object_name=related_object_name,
        )

        log_activity(
            organization_id=tagged_item.tag.team.organization_id if tagged_item.tag and tagged_item.tag.team else None,
            team_id=tagged_item.tag.team_id if tagged_item.tag else None,
            user=user,
            was_impersonated=was_impersonated,
            item_id=tagged_item.id,
            scope=scope,
            activity=activity,
            detail=Detail(
                changes=changes_between(scope, previous=before_update, current=after_update),
                name=tagged_item.tag.name if tagged_item.tag else None,
                context=context,
            ),
        )
