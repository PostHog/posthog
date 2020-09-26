from distutils.util import strtobool
from typing import Any, Dict

import posthoganalytics
from django.db.models import QuerySet
from django.db.models.signals import post_save
from django.dispatch import receiver
from rest_framework import request, serializers, viewsets
from rest_hooks.signals import raw_hook_event

from posthog.api.user import UserSerializer
from posthog.mixins import AnalyticsDestroyModelMixin
from posthog.models import Annotation


class AnnotationSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(required=False, read_only=True)

    class Meta:
        model = Annotation
        fields = [
            "id",
            "content",
            "date_marker",
            "creation_type",
            "dashboard_item",
            "created_by",
            "created_at",
            "updated_at",
            "deleted",
            "scope",
        ]
        read_only_fields = [
            "id",
            "creation_type",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Annotation:
        request = self.context["request"]
        annotation = Annotation.objects.create(
            organization=request.user.organization, team=request.user.team, created_by=request.user, **validated_data,
        )
        return annotation


class AnnotationsViewSet(AnalyticsDestroyModelMixin, viewsets.ModelViewSet):
    queryset = Annotation.objects.all()
    serializer_class = AnnotationSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        team = self.request.user.team

        if self.action == "list":  # type: ignore
            queryset = self._filter_request(self.request, queryset)
            order = self.request.GET.get("order", None)
            if order:
                queryset = queryset.order_by(order)

        return queryset.filter(team=team)

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()

        for key in filters:
            if key == "after":
                queryset = queryset.filter(created_at__gt=request.GET["after"])
            elif key == "before":
                queryset = queryset.filter(created_at__lt=request.GET["before"])
            elif key == "dashboardItemId":
                queryset = queryset.filter(dashboard_item_id=request.GET["dashboardItemId"])
            elif key == "scope":
                queryset = queryset.filter(scope=request.GET["scope"])
            elif key == "apply_all":
                queryset_method = (
                    queryset.exclude if bool(strtobool(str(request.GET["apply_all"]))) else queryset.filter
                )
                queryset = queryset_method(scope="dashboard_item")
            elif key == "deleted":
                queryset = queryset.filter(deleted=bool(strtobool(str(request.GET["deleted"]))))

        return queryset


@receiver(post_save, sender=Annotation, dispatch_uid="hook-annotation-created")
def annotation_created(sender, instance, created, raw, using, **kwargs):
    """Trigger action_defined hooks on Annotation creation."""

    if created:
        raw_hook_event.send(
            sender=None,
            event_name="annotation_created",
            instance=instance,
            payload=AnnotationSerializer(instance).data,
            user=instance.team,
        )

    if instance.created_by:
        event_name: str = "annotation created" if created else "annotation updated"
        posthoganalytics.capture(
            instance.created_by.distinct_id, event_name, instance.get_analytics_metadata(),
        )
