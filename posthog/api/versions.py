from rest_framework import permissions, serializers, viewsets

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.version import Version


class VersionSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Version
        fields = [
            "id",
            "instance_key",
            "comment",
            "created_at",
            "created_by",
            "previous_state",
        ]


class VersionsViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = Version.objects.all()
    serializer_class = VersionSerializer
    permission_classes = [permissions.IsAuthenticated]
