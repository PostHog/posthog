from typing import Any, Dict, Optional, Union

import posthoganalytics
from django.conf import settings
from django.contrib.auth import login, password_validation
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import (
    exceptions,
    generics,
    permissions,
    request,
    response,
    serializers,
    status,
    viewsets,
)

from posthog.api.user import UserSerializer
from posthog.demo import create_demo_team
from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership
from posthog.permissions import (
    CREATE_METHODS,
    OrganizationAdminWritePermissions,
    OrganizationMemberPermissions,
    UninitiatedOrCloudOnly,
)


class PremiumMultiorganizationPermissions(permissions.BasePermission):
    """Require user to have all necessary premium features on their plan for create access to the endpoint."""

    message = "You must upgrade your PostHog plan to be able to create and manage multiple organizations."

    def has_permission(self, request: request.Request, view) -> bool:
        if (
            # make multiple orgs only premium on self-hosted, since enforcement of this is not possible on Cloud
            not getattr(settings, "MULTI_TENANCY", False)
            and request.method in CREATE_METHODS
            and (
                request.user.organization is None
                or not request.user.organization.is_feature_available("organizations_projects")
            )
            and request.user.organizations.count() >= 1
        ):
            return False
        return True


class OrganizationSerializer(serializers.ModelSerializer):
    membership_level = serializers.SerializerMethodField()
    setup = (
        serializers.SerializerMethodField()
    )  # Information related to the current state of the onboarding/setup process

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "created_at",
            "updated_at",
            "membership_level",
            "personalization",
            "setup",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

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

        if instance.setup_section_2_completed:
            # As Section 2 is the last one of the setup process (as of today), if it's completed it means the setup process is done
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
        }


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        PremiumMultiorganizationPermissions,
        OrganizationMemberPermissions,
        OrganizationAdminWritePermissions,
    ]
    queryset = Organization.objects.none()
    lookup_field = "id"
    ordering = "-created_by"

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        for member in instance.members.all():
            if member.organizations.count() <= 1:
                raise exceptions.ValidationError(
                    f"Cannot remove organization since that would leave member {member.email} organization-less, which is not supported yet."
                )
        self.perform_destroy(instance)
        return response.Response(status=status.HTTP_204_NO_CONTENT)

    def get_queryset(self) -> QuerySet:
        return self.request.user.organizations.all()

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@current":
            organization = self.request.user.organization
            if organization is None:
                raise exceptions.NotFound("Current organization not found.")
            return organization
        filter_kwargs = {self.lookup_field: lookup_value}
        organization = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, organization)
        return organization


class OrganizationSignupSerializer(serializers.Serializer):
    first_name: serializers.Field = serializers.CharField(max_length=128)
    email: serializers.Field = serializers.EmailField()
    password: serializers.Field = serializers.CharField(allow_null=True)
    company_name: serializers.Field = serializers.CharField(max_length=128, required=False, allow_blank=True)
    email_opt_in: serializers.Field = serializers.BooleanField(default=True)

    def validate_password(self, value):
        if value is not None:
            password_validation.validate_password(value)
        return value

    def create(self, validated_data, **kwargs):
        is_instance_first_user: bool = not User.objects.exists()

        company_name = validated_data.pop("company_name", validated_data["first_name"])

        self._organization, self._team, self._user = User.objects.bootstrap(
            company_name=company_name, create_team=self.create_team, **validated_data,
        )
        user = self._user

        # Temp (due to FF-release [`onboarding-2822`]): Activate the setup/onboarding process if applicable
        if self.enable_new_onboarding(user):
            self._organization.setup_section_2_completed = False
            self._organization.save()

        login(
            self.context["request"], user, backend="django.contrib.auth.backends.ModelBackend",
        )

        posthoganalytics.identify(
            user.distinct_id, {"is_first_user": is_instance_first_user, "is_organization_first_user": True},
        )
        posthoganalytics.capture(
            user.distinct_id,
            "user signed up",
            properties={"is_first_user": is_instance_first_user, "is_organization_first_user": True},
        )

        return user

    def create_team(self, organization: Organization, user: User) -> Team:
        if self.enable_new_onboarding(user):
            return create_demo_team(user=user, organization=organization, request=self.context["request"])
        else:
            return Team.objects.create_with_data(user=user, organization=organization)

    def to_representation(self, instance) -> Dict:
        data = UserSerializer(instance=instance).data
        data["redirect_url"] = "/personalization" if self.enable_new_onboarding() else "/ingestion"
        return data

    def enable_new_onboarding(self, user: Optional[User] = None) -> bool:
        if user is None:
            user = self._user
        return posthoganalytics.feature_enabled("onboarding-2822", user.distinct_id) or settings.DEBUG


class OrganizationSignupViewset(generics.CreateAPIView):
    serializer_class = OrganizationSignupSerializer
    permission_classes = [UninitiatedOrCloudOnly]
