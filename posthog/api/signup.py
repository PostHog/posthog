from typing import Any, Dict, Optional, Union, cast

import posthoganalytics
from django import forms
from django.conf import settings
from django.contrib.auth import login, password_validation
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls.base import reverse
from rest_framework import exceptions, generics, permissions, response, serializers, validators
from sentry_sdk import capture_exception
from social_core.pipeline.partial import partial
from social_django.strategy import DjangoStrategy

from posthog.api.shared import UserBasicSerializer
from posthog.demo import create_demo_team
from posthog.event_usage import report_user_joined_organization, report_user_signed_up
from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationInvite
from posthog.permissions import CanCreateOrg
from posthog.tasks import user_identify
from posthog.utils import get_can_create_org, mask_email_address


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


class SignupViewset(generics.CreateAPIView):
    serializer_class = SignupSerializer
    # Enables E2E testing of signup flow
    permission_classes = (permissions.AllowAny,) if settings.E2E_TESTING else (CanCreateOrg,)


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


## Social Signup
## views & serializers
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


class SocialSignupViewset(generics.CreateAPIView):
    serializer_class = SocialSignupSerializer
    permission_classes = (CanCreateOrg,)


class TeamInviteSurrogate:
    """This reimplements parts of OrganizationInvite that enable compatibility with the old Team.signup_token."""

    def __init__(self, signup_token: str):
        team = Team.objects.select_related("organization").get(signup_token=signup_token)
        self.organization = team.organization

    def validate(*args, **kwargs) -> bool:
        return True

    def use(self, user: Any, *args, **kwargs) -> None:
        user.join(organization=self.organization)


class CompanyNameForm(forms.Form):
    companyName = forms.CharField(max_length=64)
    emailOptIn = forms.BooleanField(required=False)


def finish_social_signup(request):
    """
    TODO: DEPRECATED in favor of posthog.api.signup.SocialSignupSerializer
    """
    if not get_can_create_org():
        return redirect("/login?error=no_new_organizations")

    if request.method == "POST":
        form = CompanyNameForm(request.POST)
        if form.is_valid():
            request.session["organization_name"] = form.cleaned_data["companyName"]
            request.session["email_opt_in"] = bool(form.cleaned_data["emailOptIn"])
            return redirect(reverse("social:complete", args=[request.session["backend"]]))
    else:
        form = CompanyNameForm()
    return render(request, "signup_to_organization_company.html", {"user_name": request.session["user_name"]})


@partial
def social_create_user(strategy: DjangoStrategy, details, backend, request, user=None, *args, **kwargs):
    if user:
        return {"is_new": False}
    backend_processor = "social_create_user"
    user_email = details["email"][0] if isinstance(details["email"], (list, tuple)) else details["email"]
    user_name = (
        details["fullname"]
        or f"{details['first_name'] or ''} {details['last_name'] or ''}".strip()
        or details["username"]
    )
    strategy.session_set("user_name", user_name)
    strategy.session_set("backend", backend.name)
    from_invite = False
    invite_id = strategy.session_get("invite_id")

    if not user_email or not user_name:
        missing_attr = "email" if not user_email else "name"
        raise ValidationError(
            {missing_attr: "This field is required and was not provided by the IdP."}, code="required"
        )

    if not invite_id:

        domain_organization: Optional[Organization] = None

        # TODO: This feature is currently available only in self-hosted
        if not settings.MULTI_TENANCY:
            # Check if the user is on a whitelisted domain
            domain = user_email.split("@")[-1]
            # TODO: Handle multiple organizations with the same whitelisted domain
            domain_organization = Organization.objects.filter(domain_whitelist__contains=[domain]).first()

        if domain_organization:
            backend_processor = "domain_whitelist"
            user = User.objects.create_and_join(
                organization=domain_organization, email=user_email, password=None, first_name=user_name
            )

        else:
            organization_name = strategy.session_get("organization_name", None)
            email_opt_in = strategy.session_get("email_opt_in", None)
            if not organization_name or email_opt_in is None:
                return redirect(finish_social_signup)

            serializer = SignupSerializer(
                data={
                    "organization_name": organization_name,
                    "email_opt_in": email_opt_in,
                    "first_name": user_name,
                    "email": user_email,
                    "password": None,
                },
                context={"request": request},
            )

            serializer.is_valid(raise_exception=True)
            user = serializer.save()
    else:
        from_invite = True
        try:
            invite: Union[OrganizationInvite, TeamInviteSurrogate] = OrganizationInvite.objects.select_related(
                "organization",
            ).get(id=invite_id)
        except (OrganizationInvite.DoesNotExist, ValidationError):
            try:
                invite = TeamInviteSurrogate(invite_id)
            except Team.DoesNotExist:
                return redirect(f"/signup/{invite_id}?error_code=invalid_invite&source=social_create_user")

        try:
            invite.validate(user=None, email=user_email)
        except exceptions.ValidationError as e:
            return redirect(
                f"/signup/{invite_id}?error_code={e.get_codes()[0]}&error_detail={e.args[0]}&source=social_create_user"
            )

        try:
            user = strategy.create_user(email=user_email, first_name=user_name, password=None)
        except Exception as e:
            capture_exception(e)
            message = "Account unable to be created. This account may already exist. Please try again"
            " or use different credentials."
            return redirect(f"/signup/{invite_id}?error_code=unknown&error_detail={message}&source=social_create_user")

        invite.use(user, prevalidated=True)

    report_user_signed_up(
        distinct_id=user.distinct_id,
        is_instance_first_user=User.objects.count() == 1,
        is_organization_first_user=not from_invite,
        new_onboarding_enabled=False,
        backend_processor=backend_processor,
        social_provider=backend.name,
    )

    return {"is_new": True, "user": user}
