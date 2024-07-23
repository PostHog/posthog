from typing import Any

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
    Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/user-guides/annotations) for more information on annotations.
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
            # That's becasue annotations are restored with a PATCH request setting `deleted` to `False`
            queryset = queryset.filter(deleted=False)

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
