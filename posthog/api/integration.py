from typing import Any

from rest_framework import mixins, serializers, viewsets
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models.integration import Integration, SlackIntegration
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

    def create(self, validated_data: Any) -> Any:
        team_id = self.context["team_id"]

        if validated_data["kind"] == "slack":
            instance = SlackIntegration.integration_from_slack_response(team_id, validated_data["config"])

            return instance

        raise ValidationError("Kind not supported")


class IntegrationViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    StructuredViewSetMixin,
    viewsets.GenericViewSet,
):
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer

    authentication_classes = [
        PersonalAPIKeyAuthentication,
        SessionAuthentication,
        BasicAuthentication,
    ]
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
