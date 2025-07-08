from datetime import datetime
from typing import Any

import emoji
from django.db.models import Q, QuerySet
from django.db.models.signals import post_save
from django.dispatch import receiver
from rest_framework import filters, serializers, viewsets, pagination

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import Annotation


class AnnotationSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Annotation
        fields = [
            "id",
            "content",
            "date_marker",
            "creation_type",
            "dashboard_item",
            "dashboard_id",
            "dashboard_name",
            "insight_short_id",
            "insight_name",
            "insight_derived_name",
            "created_by",
            "created_at",
            "updated_at",
            "deleted",
            "scope",
            "recording_id",
            "is_emoji",
        ]
        read_only_fields = [
            "id",
            "insight_short_id",
            "insight_name",
            "insight_derived_name",
            "dashboard_name",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def update(self, instance: Annotation, validated_data: dict[str, Any]) -> Annotation:
        instance.team_id = self.context["team_id"]
        return super().update(instance, validated_data)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        is_emoji = attrs.get("is_emoji", False)
        content = attrs.get("content", "")

        if is_emoji and content:
            # Check if content is an emoji
            if not emoji.is_emoji(content):
                raise serializers.ValidationError("When is_emoji is True, content must be a single emoji")
        elif is_emoji and not content:
            raise serializers.ValidationError("When is_emoji is True, content cannot be empty")

        return attrs

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> Annotation:
        request = self.context["request"]
        team = self.context["get_team"]()
        annotation = Annotation.objects.create(
            organization_id=team.organization_id,
            team_id=team.id,
            created_by=request.user,
            dashboard_id=request.data.get("dashboard_id", None),
            **validated_data,
        )
        return annotation


class AnnotationsLimitOffsetPagination(pagination.LimitOffsetPagination):
    default_limit = 1000


class AnnotationsViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/data/annotations) for more information on annotations.
    """

    scope_object = "annotation"
    queryset = Annotation.objects.select_related("dashboard_item").select_related("created_by")
    serializer_class = AnnotationSerializer
    filter_backends = [filters.SearchFilter]
    pagination_class = AnnotationsLimitOffsetPagination
    search_fields = ["content"]

    def safely_get_queryset(self, queryset) -> QuerySet:
        if self.action == "list":
            queryset = queryset.order_by("-date_marker")
        if self.action != "partial_update":
            # We never want deleted items to be included in the queryset… except when we want to restore an annotation
            # That's because annotations are restored with a PATCH request setting `deleted` to `False`
            queryset = queryset.filter(deleted=False)

        scope = self.request.query_params.get("scope")
        if scope:
            # let's allow the more recently used "insight" scope to be used as "dashboard_item"
            scope = "dashboard_item" if scope == "insight" else scope
            if scope not in [scope.value for scope in Annotation.Scope]:
                raise serializers.ValidationError(f"Invalid scope: {scope}")

            queryset = queryset.filter(scope=scope)

        # Add date range filtering
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")

        date_from_parsed = None
        date_to_parsed = None

        if date_from:
            try:
                date_from_parsed = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
                queryset = queryset.filter(date_marker__gte=date_from_parsed)
            except ValueError:
                raise serializers.ValidationError("Invalid date range: date_from must be a valid ISO 8601 date")

        if date_to:
            try:
                date_to_parsed = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
                queryset = queryset.filter(date_marker__lte=date_to_parsed)
            except ValueError:
                raise serializers.ValidationError("Invalid date range: date_to must be a valid ISO 8601 date")

        if date_from_parsed and date_to_parsed and date_from_parsed > date_to_parsed:
            raise serializers.ValidationError("Invalid date range: date_from must be before date_to")

        # Add is_emoji filtering
        is_emoji = self.request.query_params.get("is_emoji")
        if is_emoji is not None:
            # Convert string to boolean (true, 1, yes -> True; false, 0, no -> False)
            is_emoji_bool = is_emoji.lower() in ("true", "1", "yes")
            queryset = queryset.filter(is_emoji=is_emoji_bool)

        return queryset

    def _filter_queryset_by_parents_lookups(self, queryset):
        team = self.team
        return queryset.filter(
            Q(scope=Annotation.Scope.ORGANIZATION, organization_id=team.organization_id) | Q(team=team)
        )


@receiver(post_save, sender=Annotation, dispatch_uid="hook-annotation-created")
def annotation_created(sender, instance, created, raw, using, **kwargs):
    if instance.created_by:
        event_name: str = "annotation created" if created else "annotation updated"
        report_user_action(instance.created_by, event_name, instance.get_analytics_metadata())
