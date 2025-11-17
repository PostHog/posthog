from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.customer_analytics.backend.constants import DEFAULT_ACTIVITY_EVENT
from products.customer_analytics.backend.models import CustomerAnalyticsConfig


class CustomerAnalyticsConfigSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = CustomerAnalyticsConfig
        fields = [
            "id",
            "activity_event",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "created_by", "updated_at"]


class CustomerAnalyticsConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = CustomerAnalyticsConfig.objects.all()
    serializer_class = CustomerAnalyticsConfigSerializer
    permission_classes = [IsAuthenticated]

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team)

    def list(self, request, *args, **kwargs):
        config, created = CustomerAnalyticsConfig.objects.get_or_create(
            team=self.team,
            defaults={
                "created_by": request.user if request.user.is_authenticated else None,
                "activity_event": DEFAULT_ACTIVITY_EVENT,
            },
        )
        serializer = self.get_serializer(config)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        config, created = CustomerAnalyticsConfig.objects.update_or_create(
            team=self.team,
            defaults={
                "activity_event": request.data.get("activity_event", {}),
                "created_by": request.user if request.user.is_authenticated else None,
            },
        )
        if created and request.user.is_authenticated:
            config.created_by = request.user
            config.save()

        serializer = self.get_serializer(config)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
