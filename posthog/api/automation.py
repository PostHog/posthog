from typing import Dict
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import Automation
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class AutomationSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Automation
        fields = [
            "id",
            "name",
            "description",
            "steps",
            "edges",
            "created_by",
            "created_at",
            # "updated_at",
            "deleted",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            # "updated_at",
        ]

    def create(self, validated_data: Dict, *args, **kwargs) -> Automation:
        validated_data["team_id"] = self.context["team_id"]
        return super().create(validated_data, *args, **kwargs)


class AutomationViewSet(StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Automation.objects.all()
    serializer_class = AutomationSerializer
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    ordering = "-created_at"
