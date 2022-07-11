from typing import Any, Dict, List, Optional, Type, cast

from dateutil.relativedelta import relativedelta
from django.core.cache import cache
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from rest_framework import exceptions, permissions, request, response, serializers, viewsets
from rest_framework.decorators import action

from posthog.api.shared import TeamBasicSerializer
from posthog.constants import AvailableFeature
from posthog.mixins import AnalyticsDestroyModelMixin
from posthog.models import Insight, Organization, Team, User
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.organization import OrganizationMembership
from posthog.models.signals import mute_selected_signals
from posthog.models.team.util import delete_bulky_postgres_data
from posthog.models.utils import generate_random_token_project
from posthog.permissions import (
    CREATE_METHODS,
    OrganizationAdminAnyPermissions,
    OrganizationAdminWritePermissions,
    ProjectMembershipNecessaryPermissions,
    TeamMemberLightManagementPermission,
)
from posthog.tasks.delete_clickhouse_data import delete_clickhouse_data


class PremiumMultiprojectPermissions(permissions.BasePermission):
    """Require user to have all necessary premium features on their plan for create access to the endpoint."""

    message = "You must upgrade your PostHog plan to be able to create and manage multiple projects."

    def has_permission(self, request: request.Request, view) -> bool:
        user = cast(User, request.user)
        if request.method in CREATE_METHODS and (
            (user.organization is None)
            or (
                user.organization.teams.exclude(is_demo=True).count() >= 1
                and not user.organization.is_feature_available(AvailableFeature.ORGANIZATIONS_PROJECTS)
            )
        ):
            return False
        return True


class TeamSerializer(serializers.ModelSerializer):
    effective_membership_level = serializers.SerializerMethodField()
    has_group_types = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = (
            "id",
            "uuid",
            "organization",
            "api_token",
            "app_urls",
            "name",
            "slack_incoming_webhook",
            "created_at",
            "updated_at",
            "anonymize_ips",
            "completed_snippet_onboarding",
            "ingested_event",
            "test_account_filters",
            "path_cleaning_filters",
            "is_demo",
            "timezone",
            "data_attributes",
            "person_display_name_properties",
            "correlation_config",
            "session_recording_opt_in",
            "effective_membership_level",
            "access_control",
            "has_group_types",
            "primary_dashboard",
            "live_events_columns",
        )
        read_only_fields = (
            "id",
            "uuid",
            "organization",
            "api_token",
            "is_demo",
            "created_at",
            "updated_at",
            "ingested_event",
            "effective_membership_level",
            "has_group_types",
        )

    def get_effective_membership_level(self, team: Team) -> Optional[OrganizationMembership.Level]:
        return team.get_effective_membership_level(self.context["request"].user.id)

    def get_has_group_types(self, team: Team) -> bool:
        return GroupTypeMapping.objects.filter(team=team).exists()

    def validate(self, attrs: Any) -> Any:
        if "primary_dashboard" in attrs and attrs["primary_dashboard"].team != self.instance:
            raise exceptions.PermissionDenied("Dashboard does not belong to this team.")

        if "access_control" in attrs:
            # Only organization-wide admins and above should be allowed to switch the project between open and private
            # If a project-only admin who is only an org member disabled this it, they wouldn't be able to reenable it
            request = self.context["request"]
            if isinstance(self.instance, Team):
                organization_id = self.instance.organization_id
            else:
                organization_id = self.context["view"].organization
            org_membership: OrganizationMembership = OrganizationMembership.objects.only("level").get(
                organization_id=organization_id, user=request.user
            )
            if org_membership.level < OrganizationMembership.Level.ADMIN:
                raise exceptions.PermissionDenied(OrganizationAdminAnyPermissions.message)

        return super().validate(attrs)

    def create(self, validated_data: Dict[str, Any], **kwargs) -> Team:
        serializers.raise_errors_on_nested_writes("create", self, validated_data)
        request = self.context["request"]
        organization = self.context["view"].organization  # Use the org we used to validate permissions
        with transaction.atomic():
            team = Team.objects.create_with_data(**validated_data, organization=organization)
            request.user.current_team = team
            request.user.save()
        return team

    def _handle_timezone_update(self, team: Team, new_timezone: str) -> None:
        hashes = (
            Insight.objects.filter(team=team, last_refresh__gt=now() - relativedelta(days=7))
            .exclude(filters_hash=None)
            .values_list("filters_hash", flat=True)
        )
        cache.delete_many(hashes)

        return

    def update(self, instance: Team, validated_data: Dict[str, Any]) -> Team:
        if "timezone" in validated_data and validated_data["timezone"] != instance.timezone:
            self._handle_timezone_update(instance, validated_data["timezone"])

        return super().update(instance, validated_data)


class TeamViewSet(AnalyticsDestroyModelMixin, viewsets.ModelViewSet):
    """
    Projects for the current organization.
    """

    serializer_class = TeamSerializer
    queryset = Team.objects.all().select_related("organization")
    permission_classes = [
        permissions.IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        PremiumMultiprojectPermissions,
    ]
    lookup_field = "id"
    ordering = "-created_by"
    organization: Optional[Organization] = None
    include_in_docs = True

    def get_queryset(self):
        # This is actually what ensures that a user cannot read/update a project for which they don't have permission
        visible_teams_ids = [
            team.id
            for team in super()
            .get_queryset()
            .filter(organization__in=cast(User, self.request.user).organizations.all())
            if team.get_effective_membership_level(self.request.user.id) is not None
        ]
        return super().get_queryset().filter(id__in=visible_teams_ids)

    def get_serializer_class(self) -> Type[serializers.BaseSerializer]:
        if self.action == "list":
            return TeamBasicSerializer
        return super().get_serializer_class()

    def get_permissions(self) -> List:
        """
        Special permissions handling for create requests as the organization is inferred from the current user.
        """
        base_permissions = [permission() for permission in self.permission_classes]
        if self.action:
            # Return early for non-actions (e.g. OPTIONS)
            if self.action == "create":
                organization = getattr(self.request.user, "organization", None)
                if not organization:
                    raise exceptions.ValidationError("You need to belong to an organization.")
                # To be used later by OrganizationAdminWritePermissions and TeamSerializer
                self.organization = organization
                base_permissions.append(OrganizationAdminWritePermissions())
            elif self.action != "list":
                # Skip TeamMemberAccessPermission for list action, as list is serialized with limited TeamBasicSerializer
                base_permissions.append(TeamMemberLightManagementPermission())
        return base_permissions

    def get_object(self):
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@current":
            team = getattr(self.request.user, "team", None)
            if team is None:
                raise exceptions.NotFound()
            return team
        queryset = self.filter_queryset(self.get_queryset())
        filter_kwargs = {self.lookup_field: lookup_value}
        try:
            team = get_object_or_404(queryset, **filter_kwargs)
        except ValueError as error:
            raise exceptions.ValidationError(str(error))
        self.check_object_permissions(self.request, team)
        return team

    def perform_destroy(self, team: Team):
        team_id = team.pk
        delete_bulky_postgres_data(team_ids=[team_id])
        delete_clickhouse_data.delay(team_ids=[team_id])
        with mute_selected_signals():
            super().perform_destroy(team)

    @action(methods=["PATCH"], detail=True)
    def reset_token(self, request: request.Request, id: str, **kwargs) -> response.Response:
        team = self.get_object()
        team.api_token = generate_random_token_project()
        team.save()
        return response.Response(TeamSerializer(team, context=self.get_serializer_context()).data)
