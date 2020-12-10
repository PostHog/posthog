from typing import Any, Dict

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, permissions, request, response, serializers, viewsets
from rest_framework.decorators import action

from posthog.models import Team
from posthog.models.utils import generate_random_token
from posthog.permissions import (
    CREATE_METHODS,
    OrganizationAdminWritePermissions,
    OrganizationMemberPermissions,
    ProjectMembershipNecessaryPermissions,
)

from .organization import OrganizationSignupSerializer, OrganizationSignupViewset


class PremiumMultiprojectPermissions(permissions.BasePermission):
    """Require user to have all necessary premium features on their plan for create access to the endpoint."""

    message = "You must upgrade your PostHog plan to be able to create and manage multiple projects."

    def has_permission(self, request: request.Request, view) -> bool:
        if request.method in CREATE_METHODS and (
            (request.user.organization is None)
            or (
                request.user.organization.teams.count() >= 1
                and not request.user.organization.is_feature_available("organizations_projects")
            )
        ):
            return False
        return True


class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = (
            "id",
            "organization",
            "api_token",
            "app_urls",
            "name",
            "slack_incoming_webhook",
            "event_names",
            "event_properties",
            "event_properties_numerical",
            "created_at",
            "updated_at",
            "anonymize_ips",
            "completed_snippet_onboarding",
            "ingested_event",
            "uuid",
            "opt_out_capture",
        )
        read_only_fields = (
            "id",
            "uuid",
            "organization",
            "api_token",
            "event_names",
            "event_properties",
            "event_properties_numerical",
            "created_at",
            "updated_at",
            "ingested_event",
            "opt_out_capture",
        )

    def create(self, validated_data: Dict[str, Any], **kwargs) -> Team:
        serializers.raise_errors_on_nested_writes("create", self, validated_data)
        request = self.context["request"]
        organization = request.user.organization
        if organization is None:
            raise exceptions.ValidationError("You need to belong to an organization first!")
        with transaction.atomic():
            validated_data.setdefault("completed_snippet_onboarding", True)
            team = Team.objects.create_with_data(**validated_data, organization=organization)
            request.user.current_team = team
            request.user.save()
        return team


class TeamViewSet(viewsets.ModelViewSet):
    serializer_class = TeamSerializer
    queryset = Team.objects.all()
    permission_classes = [
        permissions.IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        PremiumMultiprojectPermissions,
        OrganizationMemberPermissions,
        OrganizationAdminWritePermissions,
    ]
    lookup_field = "id"
    ordering = "-created_by"

    def get_queryset(self):
        queryset = super().get_queryset().filter(organization__in=self.request.user.organizations.all())
        return queryset

    def get_object(self):
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@current":
            team = self.request.user.team
            if team is None:
                raise exceptions.NotFound("Current project not found.")
            return team
        queryset = self.filter_queryset(self.get_queryset())
        filter_kwargs = {self.lookup_field: lookup_value}
        try:
            team = get_object_or_404(queryset, **filter_kwargs)
        except ValueError as error:
            raise exceptions.ValidationError(str(error))
        self.check_object_permissions(self.request, team)
        return team

    @action(methods=["PATCH"], detail=True)
    def reset_token(self, request: request.Request, id: str, **kwargs) -> response.Response:
        team = self.get_object()
        team.api_token = generate_random_token()
        team.save()
        return response.Response(TeamSerializer(team).data)
