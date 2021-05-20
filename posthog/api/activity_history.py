from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import DashboardItem


class ActivityHistorySerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = DashboardItem
        fields = [
            "id",
            "parent",
            "name",
            "filters",
            "filters_hash",
            "order",
            "deleted",
            "layouts",
            "color",
            "last_refresh",
            "refreshing",
            "created_at",
            "saved",
            "created_by",
        ]
        read_only_fields = (
            "created_by",
            "created_at",
        )


class ActivityHistoryViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = DashboardItem.objects.exclude(parent__isnull=True)
    serializer_class = ActivityHistorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        parent = self.request.query_params["parent"]
        return DashboardItem.objects.filter(parent=parent)
