from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.warehouse.models import DataWarehouseModelPath


class DataWarehouseModelPathSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    columns = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DataWarehouseModelPath


class DataWarehouseModelViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"

    queryset = DataWarehouseModelPath.objects.all()
    serializer_class = DataWarehouseModelPathSerializer
