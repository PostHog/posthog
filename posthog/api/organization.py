from typing import Any, Dict, List, Optional, cast

from django.conf import settings
from django.db.models import Model, QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, permissions, serializers, viewsets
from rest_framework.request import Request

from posthog.api.shared import TeamBasicSerializer
from posthog.constants import AvailableFeature
from posthog.event_usage import report_organization_deleted
from posthog.models import Organization, User
from posthog.models.organization import OrganizationMembership
from posthog.models.signals import mute_selected_signals
from posthog.models.team.util import delete_bulky_postgres_data
from posthog.permissions import (
    CREATE_METHODS,
    OrganizationAdminWritePermissions,
    OrganizationMemberPermissions,
    extract_organization,
)
from posthog.tasks.delete_clickhouse_data import delete_clickhouse_data


class PremiumMultiorganizationPermissions(permissions.BasePermission):
    """Require user to have all necessary premium features on their plan for create access to the endpoint."""

    message = "You must upgrade your PostHog plan to be able to create and manage multiple organizations."

    def has_permission(self, request: Request, view) -> bool:
        user = cast(User, request.user)
        if (
            # Make multiple orgs only premium on self-hosted, since enforcement of this wouldn't make sense on Cloud
            not settings.MULTI_TENANCY
            and request.method in CREATE_METHODS
            and (
                user.organization is None
                or not user.organization.is_feature_available(AvailableFeature.ORGANIZATIONS_PROJECTS)
            )
            and user.organizations.count() >= 1
        ):
            return False
        return True


class OrganizationPermissionsWithDelete(OrganizationAdminWritePermissions):
    def has_object_permission(self, request: Request, view, object: Model) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        # TODO: Optimize so that this computation is only done once, on `OrganizationMemberPermissions`
        organization = extract_organization(object)
        min_level = (
            OrganizationMembership.Level.OWNER if request.method == "DELETE" else OrganizationMembership.Level.ADMIN
        )
        return (
            OrganizationMembership.objects.get(user=cast(User, request.user), organization=organization).level
            >= min_level
        )


class OrganizationSerializer(serializers.ModelSerializer):
    membership_level = serializers.SerializerMethodField()
    teams = serializers.SerializerMethodField()
    metadata = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "slug",
            "created_at",
            "updated_at",
            "membership_level",
            "plugins_access_level",
            "teams",
            "available_features",
            "is_member_join_email_enabled",
            "metadata",
        ]
        read_only_fields = [
            "id",
            "slug",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "slug": {
                "required": False,
            },  # slug is not required here as it's generated automatically for new organizations
        }

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Organization:
        serializers.raise_errors_on_nested_writes("create", self, validated_data)
        organization, _, _ = Organization.objects.bootstrap(self.context["request"].user, **validated_data)
        return organization

    def get_membership_level(self, organization: Organization) -> Optional[OrganizationMembership.Level]:
        membership = OrganizationMembership.objects.filter(
            organization=organization, user=self.context["request"].user,
        ).first()
        return membership.level if membership is not None else None

    def get_teams(self, instance: Organization) -> List[Dict[str, Any]]:
        teams = cast(
            List[Dict[str, Any]], TeamBasicSerializer(instance.teams.all(), context=self.context, many=True).data
        )
        visible_teams = [team for team in teams if team["effective_membership_level"] is not None]
        return visible_teams

    def get_metadata(self, instance: Organization) -> Dict[str, int]:
        output = {
            "taxonomy_set_events_count": 0,
            "taxonomy_set_properties_count": 0,
        }

        try:
            from ee.models.event_definition import EnterpriseEventDefinition
            from ee.models.property_definition import EnterprisePropertyDefinition
        except ImportError:
            return output

        output["taxonomy_set_events_count"] = EnterpriseEventDefinition.objects.exclude(
            description="", tagged_items__isnull=True
        ).count()
        output["taxonomy_set_properties_count"] = EnterprisePropertyDefinition.objects.exclude(
            description="", tagged_items__isnull=True
        ).count()

        return output


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        OrganizationMemberPermissions,
        OrganizationPermissionsWithDelete,
    ]
    queryset = Organization.objects.none()
    lookup_field = "id"
    ordering = "-created_by"

    def get_permissions(self):
        if self.request.method == "POST":
            # Cannot use `OrganizationMemberPermissions` or `OrganizationAdminWritePermissions`
            # because they require an existing org, unneded anyways because permissions are organization-based
            return [permission() for permission in [permissions.IsAuthenticated, PremiumMultiorganizationPermissions]]
        return super().get_permissions()

    def get_queryset(self) -> QuerySet:
        return cast(User, self.request.user).organizations.all()

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@current":
            organization = cast(User, self.request.user).organization
            if organization is None:
                raise exceptions.NotFound("Current organization not found.")
        else:
            filter_kwargs = {self.lookup_field: lookup_value}
            organization = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, organization)
        return organization

    def perform_destroy(self, organization: Organization):
        user = cast(User, self.request.user)
        report_organization_deleted(user, organization)
        team_ids = [team.pk for team in organization.teams.all()]
        delete_clickhouse_data.delay(team_ids=team_ids)
        delete_bulky_postgres_data(team_ids=team_ids)
        with mute_selected_signals():
            super().perform_destroy(organization)
