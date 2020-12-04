from typing import Any, Dict

import posthoganalytics
from django.conf import settings
from django.contrib.auth import login, password_validation
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, generics, permissions, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework_extensions.routers import NestedRouterMixin

from posthog.api.user import UserSerializer
from posthog.models import Team, User
from posthog.models.utils import generate_random_token
from posthog.permissions import (
    CREATE_METHODS,
    OrganizationAdminWritePermissions,
    OrganizationMemberPermissions,
    ProjectMembershipNecessaryPermissions,
    UninitiatedOrCloudOnly,
)


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


class TeamSignupSerializer(serializers.Serializer):
    first_name: serializers.Field = serializers.CharField(max_length=128)
    email: serializers.Field = serializers.EmailField()
    password: serializers.Field = serializers.CharField()
    company_name: serializers.Field = serializers.CharField(max_length=128, required=False, allow_blank=True)
    email_opt_in: serializers.Field = serializers.BooleanField(default=True)

    def validate_password(self, value):
        password_validation.validate_password(value)
        return value

    def create(self, validated_data, **kwargs):
        is_first_user: bool = not User.objects.exists()
        realm: str = "cloud" if getattr(settings, "MULTI_TENANCY", False) else "hosted"

        company_name = validated_data.pop("company_name", validated_data["first_name"])
        self._organization, self._team, self._user = User.objects.bootstrap(company_name=company_name, **validated_data)
        user = self._user
        login(
            self.context["request"], user, backend="django.contrib.auth.backends.ModelBackend",
        )

        posthoganalytics.capture(
            user.distinct_id,
            "user signed up",
            properties={"is_first_user": is_first_user, "is_organization_first_user": True},
        )

        posthoganalytics.identify(
            user.distinct_id, properties={"email": user.email, "realm": realm, "ee_available": settings.EE_AVAILABLE},
        )

        return user

    def to_representation(self, instance):
        serializer = UserSerializer(instance=instance)
        return serializer.data


class TeamSignupViewset(generics.CreateAPIView):
    serializer_class = TeamSignupSerializer
    permission_classes = [UninitiatedOrCloudOnly]
