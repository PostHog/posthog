from typing import Any, Dict, Optional, cast

import posthoganalytics
from django.conf import settings
from django.contrib.auth import login, password_validation
from django.db import transaction
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
from posthog.models import Organization, User
from posthog.models.organization import OrganizationInvite, OrganizationMembership
from posthog.permissions import (
    CREATE_METHODS,
    OrganizationAdminWritePermissions,
    OrganizationMemberPermissions,
    UninitiatedOrCloudOnly,
)
from posthog.utils import get_instance_realm


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
    membership_level = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Organization
        fields = ["id", "name", "created_at", "updated_at", "membership_level"]
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
            organization=organization, user=self.context["request"].user
        ).first()
        return membership.level if membership is not None else None


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
    password: serializers.Field = serializers.CharField()
    company_name: serializers.Field = serializers.CharField(max_length=128, required=False, allow_blank=True)
    email_opt_in: serializers.Field = serializers.BooleanField(default=True)

    def validate_password(self, value):
        password_validation.validate_password(value)
        return value

    def create(self, validated_data, **kwargs):
        is_first_user: bool = not User.objects.exists()

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
            user.distinct_id,
            properties={"email": user.email, "realm": get_instance_realm(), "ee_available": settings.EE_AVAILABLE},
        )

        return user

    def to_representation(self, instance):
        serializer = UserSerializer(instance=instance)
        return serializer.data


class OrganizationSignupViewset(generics.CreateAPIView):
    serializer_class = OrganizationSignupSerializer
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

        user = cast(User, self.context["request"].user)

        invite_id = self.context["view"].kwargs.get("invite_id")

        try:
            invite: OrganizationInvite = OrganizationInvite.objects.select_related("organization").get(id=invite_id)
        except (OrganizationInvite.DoesNotExist):
            raise serializers.ValidationError("The provided invite ID is not valid.")

        is_new_user: bool = False

        with transaction.atomic():
            if not user.is_authenticated:
                is_new_user = True
                user = User.objects.create_user(
                    invite.target_email,
                    validated_data.pop("password"),
                    validated_data.pop("first_name"),
                    **validated_data,
                )
                user.set_password

            try:
                invite.use(user)
            except ValueError as e:
                raise serializers.ValidationError(str(e))

        posthoganalytics.identify(
            user.distinct_id,
            properties={"email": user.email, "realm": get_instance_realm(), "ee_available": settings.EE_AVAILABLE},
        )

        if is_new_user:
            posthoganalytics.capture(
                user.distinct_id,
                "user signed up",
                properties={"is_first_user": False, "is_organization_first_user": False},
            )

            login(
                self.context["request"], user, backend="django.contrib.auth.backends.ModelBackend",
            )

        else:
            posthoganalytics.capture(
                user.distinct_id,
                "user joined organization",
                properties={
                    "user_memberships_count": user.organization_memberships.count(),
                    "organization_project_count": user.organization.teams.count(),
                    "organization_users_count": user.organization.memberships.count(),
                },
            )

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
        except (OrganizationInvite.DoesNotExist):
            raise serializers.ValidationError("The provided invite ID is not valid.")

        user = request.user if request.user.is_authenticated else None

        try:
            invite.validate(user=user)
        except ValueError as e:
            raise serializers.ValidationError(str(e))

        return response.Response({"target_email": invite.target_email})
