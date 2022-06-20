from typing import Any
from rest_framework import mixins, serializers, viewsets
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models.instance_setting import get_instance_setting
from posthog.models.integration import Integration
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class IntegrationSerializer(serializers.ModelSerializer):
    """Standard Inteegration serializer."""

    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Integration
        fields = [
            "id",
            "kind",
            "config",
            "created_at",
            "created_by",
            "errors",
        ]
        read_only_fields = ["id", "created_at", "created_by", "errors"]


class IntegrationViewSet(
    mixins.RetrieveModelMixin, mixins.ListModelMixin, StructuredViewSetMixin, viewsets.GenericViewSet
):
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer

    authentication_classes = [
        PersonalAPIKeyAuthentication,
        SessionAuthentication,
        BasicAuthentication,
    ]
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
