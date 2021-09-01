from django.db.models import QuerySet
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.mixins import AnalyticsDestroyModelMixin
from posthog.models.tour import Tour
from posthog.permissions import ProjectMembershipNecessaryPermissions


class TourSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tour
        fields = [
            "uuid",
            "cohort",
            "team",
            "name",
            "trigger_url_regex",
            "delay_ms",
            "is_active",
            "steps",
        ]


class TourViewSet(StructuredViewSetMixin, AnalyticsDestroyModelMixin, viewsets.ModelViewSet):
    queryset = Tour.objects.all()
    serializer_class = TourSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        return queryset.order_by("-created_at")
