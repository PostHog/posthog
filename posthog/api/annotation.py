from typing import Any, Dict

from django.db.models import Q, QuerySet
from django.db.models.signals import post_save
from django.dispatch import receiver
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import request, filters, serializers, viewsets
from rest_framework.permissions import IsAuthenticated


from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import Annotation
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


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
            "insight_short_id",
            "insight_name",
            "created_by",
            "created_at",
            "updated_at",
            "deleted",
            "scope",
            "recording_timestamp",
            "session_id",
        ]
        read_only_fields = [
            "id",
            "insight_short_id",
            "insight_name",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def update(self, instance: Annotation, validated_data: Dict[str, Any]) -> Annotation:
        instance.team_id = self.context["team_id"]
        return super().update(instance, validated_data)

    def create(self, validated_data: Dict[str, Any], *args: Any, **kwargs: Any) -> Annotation:
        request = self.context["request"]
        team = self.context["get_team"]()
        annotation = Annotation.objects.create(
            organization_id=team.organization_id, team_id=team.id, created_by=request.user, **validated_data
        )
        return annotation


class AnnotationsViewSet(StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete annotations. [See docs](https://posthog.com/docs/user-guides/annotations) for more information on annotations.
    """

    queryset = Annotation.objects.select_related("dashboard_item")
    serializer_class = AnnotationSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    filterset_fields = ["scope", "session_id"]
    search_fields = ["content"]
    default_limit = 500

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()

        for key in filters:
            if key == "session_id":
                queryset = queryset.filter(scope="recording").filter(session_id=filters["session_id"])
            elif key == "search":
                queryset = queryset.filter(content__icontains=request.GET["search"])

        return queryset

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset().select_related("created_by")
        if self.action == "list":
            order = self.request.GET.get("order", None)
            if order:
                queryset = queryset.order_by(order)
            else:
                queryset = queryset.order_by("-date_marker")

            queryset = self._filter_request(self.request, queryset)
        if self.action != "partial_update":
            # We never want deleted items to be included in the queryset… except when we want to restore an annotation
            # That's becasue annotations are restored with a PATCH request setting `deleted` to `False`
            queryset = queryset.filter(deleted=False)

        return queryset

    def filter_queryset_by_parents_lookups(self, queryset):
        team = self.team
        return queryset.filter(
            Q(scope=Annotation.Scope.ORGANIZATION, organization_id=team.organization_id) | Q(team=team)
        )


@receiver(post_save, sender=Annotation, dispatch_uid="hook-annotation-created")
def annotation_created(sender, instance, created, raw, using, **kwargs):
    if instance.created_by:
        event_name: str = "annotation created" if created else "annotation updated"
        report_user_action(instance.created_by, event_name, instance.get_analytics_metadata())
