from typing import Any, Dict, List, Optional, Union, cast

from django.db.models import Model, QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, permissions, serializers, viewsets
from rest_framework.request import Request

from posthog import settings
from posthog.api.shared import TeamBasicSerializer
from posthog.cloud_utils import is_cloud
from posthog.constants import AvailableFeature
from posthog.event_usage import report_organization_deleted
from posthog.models import Organization, User
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.organization import OrganizationMembership
from posthog.models.signals import mute_selected_signals
from posthog.models.team.util import delete_bulky_postgres_data
from posthog.permissions import (
    CREATE_METHODS,
    OrganizationAdminWritePermissions,
    OrganizationMemberPermissions,
    extract_organization,
)
from posthog.user_permissions import UserPermissions, UserPermissionsSerializerMixin


class PremiumMultiorganizationPermissions(permissions.BasePermission):
    """Require user to have all necessary premium features on their plan for create access to the endpoint."""

    message = "You must upgrade your PostHog plan to be able to create and manage multiple organizations."

    def has_permission(self, request: Request, view) -> bool:
        user = cast(User, request.user)
        if (
            # Make multiple orgs only premium on self-hosted, since enforcement of this wouldn't make sense on Cloud
            not is_cloud()
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


class OrganizationSerializer(serializers.ModelSerializer, UserPermissionsSerializerMixin):
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
            "available_product_features",
            "is_member_join_email_enabled",
            "metadata",
            "customer_id",
            "enforce_2fa",
        ]
        read_only_fields = [
            "id",
            "slug",
            "created_at",
            "updated_at",
            "membership_level",
            "plugins_access_level",
            "teams",
            "available_features",
            "available_product_features",
            "metadata",
            "customer_id",
        ]
        extra_kwargs = {
            "slug": {
                "required": False,
            },  # slug is not required here as it's generated automatically for new organizations
        }

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Organization:
        serializers.raise_errors_on_nested_writes("create", self, validated_data)
        user = self.context["request"].user
        organization, _, _ = Organization.objects.bootstrap(user, **validated_data)

        return organization

    def get_membership_level(self, organization: Organization) -> Optional[OrganizationMembership.Level]:
        membership = self.user_permissions.organization_memberships.get(organization.pk)
        return membership.level if membership is not None else None

    def get_teams(self, instance: Organization) -> List[Dict[str, Any]]:
        teams = cast(
            List[Dict[str, Any]],
            TeamBasicSerializer(instance.teams.all(), context=self.context, many=True).data,
        )
        visible_team_ids = set(self.user_permissions.team_ids_visible_for_user)
        return [team for team in teams if team["id"] in visible_team_ids]

    def get_metadata(self, instance: Organization) -> Dict[str, Union[str, int, object]]:
        return {
            "instance_tag": settings.INSTANCE_TAG,
        }


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
            return [
                permission()
                for permission in [
                    permissions.IsAuthenticated,
                    PremiumMultiorganizationPermissions,
                ]
            ]
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
        delete_bulky_postgres_data(team_ids=team_ids)
        with mute_selected_signals():
            super().perform_destroy(organization)
        # Once the organization is deleted, queue deletion of associated data
        AsyncDeletion.objects.bulk_create(
            [
                AsyncDeletion(
                    deletion_type=DeletionType.Team,
                    team_id=team_id,
                    key=str(team_id),
                    created_by=user,
                )
                for team_id in team_ids
            ],
            ignore_conflicts=True,
        )

    def get_serializer_context(self) -> Dict[str, Any]:
        return {
            **super().get_serializer_context(),
            "user_permissions": UserPermissions(cast(User, self.request.user)),
        }
