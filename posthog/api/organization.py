from typing import Any, Dict, List, Optional, Union, cast

import posthoganalytics
from django.conf import settings
from django.contrib.auth import login, password_validation
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from django.urls.base import reverse
from rest_framework import exceptions, generics, permissions, response, serializers, status, viewsets
from rest_framework.request import Request

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.user import UserSerializer
from posthog.demo import create_demo_team
from posthog.event_usage import report_onboarding_completed, report_user_joined_organization, report_user_signed_up
from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationInvite, OrganizationMembership
from posthog.permissions import (
    CREATE_METHODS,
    OrganizationAdminWritePermissions,
    OrganizationMemberPermissions,
    UninitiatedOrCloudOnly,
)
from posthog.tasks import user_identify
from posthog.utils import mask_email_address


class PremiumMultiorganizationPermissions(permissions.BasePermission):
    """Require user to have all necessary premium features on their plan for create access to the endpoint."""

    message = "You must upgrade your PostHog plan to be able to create and manage multiple organizations."

    def has_permission(self, request: Request, view) -> bool:
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
            "setup_section_2_completed",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {"setup_section_2_completed": {"write_only": True}}  # `setup` is used for reading this attribute

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
            "has_invited_team_members": instance.invites.exists() or instance.members.count() > 1,
        }


class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        OrganizationMemberPermissions,
        OrganizationAdminWritePermissions,
    ]
    queryset = Organization.objects.none()
    lookup_field = "id"
    ordering = "-created_by"

    def get_permissions(self) -> List[permissions.BasePermission]:
        if self.request.method == "POST":
            # Cannot use `OrganizationMemberPermissions` or `OrganizationAdminWritePermissions`
            # because they require an existing org, unneded anyways because permissions are organization-based
            return [permission() for permission in [permissions.IsAuthenticated, PremiumMultiorganizationPermissions]]
        return super().get_permissions()

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
    organization_name: serializers.Field = serializers.CharField(max_length=128, required=False, allow_blank=True)
    email_opt_in: serializers.Field = serializers.BooleanField(default=True)

    def validate_password(self, value):
        if value is not None:
            password_validation.validate_password(value)
        return value

    def create(self, validated_data, **kwargs):
        is_instance_first_user: bool = not User.objects.exists()

        organization_name = validated_data.pop("organization_name", validated_data["first_name"])

        self._organization, self._team, self._user = User.objects.bootstrap(
            organization_name=organization_name, create_team=self.create_team, **validated_data,
        )
        user = self._user

        # Temp (due to FF-release [`new-onboarding-2822`]): Activate the setup/onboarding process if applicable
        if self.enable_new_onboarding(user):
            self._organization.setup_section_2_completed = False
            self._organization.save()

        login(
            self.context["request"], user, backend="django.contrib.auth.backends.ModelBackend",
        )

        report_user_signed_up(
            user.distinct_id,
            is_instance_first_user=is_instance_first_user,
            is_organization_first_user=True,
            new_onboarding_enabled=(not self._organization.setup_section_2_completed),
            backend_processor="OrganizationSignupSerializer",
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
        return posthoganalytics.feature_enabled("new-onboarding-2822", user.distinct_id) or settings.DEBUG


class OrganizationSocialSignupSerializer(serializers.Serializer):
    """
    Signup serializer when the account is created using social authentication.
    Pre-processes information not obtained from SSO provider to create organization.
    """

    organization_name: serializers.Field = serializers.CharField(max_length=128)
    email_opt_in: serializers.Field = serializers.BooleanField(default=True)

    def create(self, validated_data, **kwargs):
        request = self.context["request"]

        if not request.session.get("backend"):
            raise serializers.ValidationError(
                "Inactive social login session. Go to /login and log in before continuing.",
            )

        request.session["organization_name"] = validated_data["organization_name"]
        request.session["email_opt_in"] = validated_data["email_opt_in"]
        request.session.set_expiry(3600)  # 1 hour to complete process
        return {"continue_url": reverse("social:complete", args=[request.session["backend"]])}

    def to_representation(self, instance: Any) -> Any:
        return self.instance


class OrganizationSignupViewset(generics.CreateAPIView):
    serializer_class = OrganizationSignupSerializer
    permission_classes = (UninitiatedOrCloudOnly,)


class OrganizationSocialSignupViewset(generics.CreateAPIView):
    serializer_class = OrganizationSocialSignupSerializer
    permission_classes = (UninitiatedOrCloudOnly,)


class OrganizationInviteSignupSerializer(serializers.Serializer):
    first_name: serializers.Field = serializers.CharField(max_length=128, required=False)
    password: serializers.Field = serializers.CharField(required=False)
    email_opt_in: serializers.Field = serializers.BooleanField(default=True)

    def validate_password(self, value):
        password_validation.validate_password(value)
        return value

    def to_representation(self, instance):
        serializer = UserSerializer(instance=instance)
        return serializer.data

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:

        if "request" not in self.context or not self.context["request"].user.is_authenticated:
            # If there's no authenticated user and we're creating a new one, attributes are required.

            for attr in ["first_name", "password"]:
                if not data.get(attr):
                    raise serializers.ValidationError({attr: "This field is required."}, code="required")

        return data

    def create(self, validated_data, **kwargs):
        if "view" not in self.context or not self.context["view"].kwargs.get("invite_id"):
            raise serializers.ValidationError("Please provide an invite ID to continue.")

        user: Optional[User] = None
        is_new_user: bool = False

        if self.context["request"].user.is_authenticated:
            user = cast(User, self.context["request"].user)

        invite_id = self.context["view"].kwargs.get("invite_id")

        try:
            invite: OrganizationInvite = OrganizationInvite.objects.select_related("organization").get(id=invite_id)
        except (OrganizationInvite.DoesNotExist):
            raise serializers.ValidationError("The provided invite ID is not valid.")

        with transaction.atomic():
            if not user:
                is_new_user = True
                user = User.objects.create_user(
                    invite.target_email,
                    validated_data.pop("password"),
                    validated_data.pop("first_name"),
                    **validated_data,
                )

            try:
                invite.use(user)
            except ValueError as e:
                raise serializers.ValidationError(str(e))

        if is_new_user:
            login(
                self.context["request"], user, backend="django.contrib.auth.backends.ModelBackend",
            )

            report_user_signed_up(
                user.distinct_id,
                is_instance_first_user=False,
                is_organization_first_user=False,
                new_onboarding_enabled=(not invite.organization.setup_section_2_completed),
                backend_processor="OrganizationInviteSignupSerializer",
            )

        else:
            report_user_joined_organization(organization=invite.organization, current_user=user)

        # Update user props
        user_identify.identify_task.delay(user_id=user.id)

        return user


class OrganizationInviteSignupViewset(generics.CreateAPIView):
    serializer_class = OrganizationInviteSignupSerializer
    permission_classes = (permissions.AllowAny,)

    def get(self, request, *args, **kwargs):
        """
        Pre-validates an invite code.
        """

        invite_id = kwargs.get("invite_id")

        if not invite_id:
            raise exceptions.ValidationError("Please provide an invite ID to continue.")

        try:
            invite: OrganizationInvite = OrganizationInvite.objects.get(id=invite_id)
        except (OrganizationInvite.DoesNotExist, ValidationError):
            raise serializers.ValidationError("The provided invite ID is not valid.")

        user = request.user if request.user.is_authenticated else None

        invite.validate(user=user)

        return response.Response(
            {
                "id": str(invite.id),
                "target_email": mask_email_address(invite.target_email),
                "first_name": invite.first_name,
                "organization_name": invite.organization.name,
            }
        )


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
