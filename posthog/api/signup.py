from typing import Any, Dict, Optional, cast

import posthoganalytics
from django.conf import settings
from django.contrib.auth import login, password_validation
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.urls.base import reverse
from rest_framework import exceptions, generics, permissions, response, serializers, validators

from posthog.api.shared import UserBasicSerializer
from posthog.demo import create_demo_team
from posthog.event_usage import report_user_joined_organization, report_user_signed_up
from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationInvite
from posthog.permissions import CanCreateOrg
from posthog.tasks import user_identify
from posthog.utils import mask_email_address


class SignupSerializer(serializers.Serializer):
    first_name: serializers.Field = serializers.CharField(max_length=128)
    email: serializers.Field = serializers.EmailField(
        validators=[
            validators.UniqueValidator(
                queryset=User.objects.all(), message="There is already an account with this email address."
            )
        ]
    )
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
            return create_demo_team(organization=organization)
        else:
            return Team.objects.create_with_data(user=user, organization=organization)

    def to_representation(self, instance) -> Dict:
        data = UserBasicSerializer(instance=instance).data
        data["redirect_url"] = "/personalization" if self.enable_new_onboarding() else "/ingestion"
        return data

    def enable_new_onboarding(self, user: Optional[User] = None) -> bool:
        if user is None:
            user = self._user
        return posthoganalytics.feature_enabled("new-onboarding-2822", user.distinct_id)


class SocialSignupSerializer(serializers.Serializer):
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


class SignupViewset(generics.CreateAPIView):
    serializer_class = SignupSerializer
    # Enables E2E testing of signup flow
    permission_classes = (permissions.AllowAny,) if settings.E2E_TESTING else (CanCreateOrg,)


class SocialSignupViewset(generics.CreateAPIView):
    serializer_class = SocialSignupSerializer
    permission_classes = (CanCreateOrg,)


class InviteSignupSerializer(serializers.Serializer):
    first_name: serializers.Field = serializers.CharField(max_length=128, required=False)
    password: serializers.Field = serializers.CharField(required=False)
    email_opt_in: serializers.Field = serializers.BooleanField(default=True)

    def validate_password(self, value):
        password_validation.validate_password(value)
        return value

    def to_representation(self, instance):
        serializer = UserBasicSerializer(instance=instance)
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
                try:
                    user = User.objects.create_user(
                        invite.target_email,
                        validated_data.pop("password"),
                        validated_data.pop("first_name"),
                        **validated_data,
                    )
                except IntegrityError:
                    raise serializers.ValidationError(
                        f"There already exists an account with email address {invite.target_email}. Please log in instead."
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


class InviteSignupViewset(generics.CreateAPIView):
    serializer_class = InviteSignupSerializer
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
