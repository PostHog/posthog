from typing import Any, Dict, List, Optional, Union, cast

from django.conf import settings
from django.db.models import Model, QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, permissions, response, serializers, viewsets
from rest_framework.request import Request

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import TeamBasicSerializer
from posthog.constants import AvailableFeature
from posthog.event_usage import report_onboarding_completed
from posthog.exceptions import EnterpriseFeatureException
from posthog.mixins import AnalyticsDestroyModelMixin
from posthog.models import Organization, User
from posthog.models.organization import OrganizationMembership
from posthog.permissions import (
    CREATE_METHODS,
    OrganizationAdminWritePermissions,
    OrganizationMemberPermissions,
    extract_organization,
)


class PremiumMultiorganizationPermissions(permissions.BasePermission):
    """Require user to have all necessary premium features on their plan for create access to the endpoint."""

    message = "You must upgrade your PostHog plan to be able to create and manage multiple organizations."

    def has_permission(self, request: Request, view) -> bool:
        user = cast(User, request.user)
        if (
            # make multiple orgs only premium on self-hosted, since enforcement of this is not possible on Cloud
            not getattr(settings, "MULTI_TENANCY", False)
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
    setup = (
        serializers.SerializerMethodField()
    )  # Information related to the current state of the onboarding/setup process
    teams = TeamBasicSerializer(many=True, read_only=True)

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "slug",
            "created_at",
            "updated_at",
            "membership_level",
            "personalization",
            "setup",
            "setup_section_2_completed",
            "plugins_access_level",
            "teams",
            "available_features",
            "domain_whitelist",
            "is_member_join_email_enabled",
        ]
        read_only_fields = [
            "id",
            "slug",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "setup_section_2_completed": {"write_only": True},  # for reading this attribute, `setup` is used
            "slug": {
                "required": False
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

    def get_setup(self, instance: Organization) -> Dict[str, Union[bool, int, str, None]]:
        if not instance.is_onboarding_active:
            # As Section 2 is the last one of the setup process (as of today),
            # if it's completed it means the setup process is done
            return {"is_active": False, "current_section": None}

        non_demo_team_id = next((team.pk for team in instance.teams.filter(is_demo=False)), None)
        any_project_ingested_events = instance.teams.filter(is_demo=False, ingested_event=True).exists()
        any_project_completed_snippet_onboarding = instance.teams.filter(
            is_demo=False, completed_snippet_onboarding=True,
        ).exists()

        current_section = 1
        if non_demo_team_id and any_project_ingested_events and any_project_completed_snippet_onboarding:
            # All steps from section 1 completed, move on to section 2
            current_section = 2

        return {
            "is_active": True,
            "current_section": current_section,
            "any_project_ingested_events": any_project_ingested_events,
            "any_project_completed_snippet_onboarding": any_project_completed_snippet_onboarding,
            "non_demo_team_id": non_demo_team_id,
            "has_invited_team_members": instance.invites.exists() or instance.members.count() > 1,
        }


class OrganizationViewSet(AnalyticsDestroyModelMixin, viewsets.ModelViewSet):
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


class OrganizationOnboardingViewset(StructuredViewSetMixin, viewsets.GenericViewSet):

    serializer_class = OrganizationSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        OrganizationMemberPermissions,
    ]

    def create(self, request, *args, **kwargs):
        # Complete onboarding
        instance: Organization = self.organization
        self.check_object_permissions(request, instance)

        if not instance.is_onboarding_active:
            raise exceptions.ValidationError("Onboarding already completed.")

        instance.complete_onboarding()

        report_onboarding_completed(organization=instance, current_user=request.user)

        serializer = self.get_serializer(instance=instance)
        return response.Response(serializer.data)
