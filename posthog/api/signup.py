from typing import Any, Dict, Optional, Union, cast
from urllib.parse import urlencode

import structlog
from django import forms
from django.conf import settings
from django.contrib.auth import login, password_validation
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from django.urls.base import reverse
from django.utils import timezone
from rest_framework import exceptions, generics, permissions, response, serializers, validators
from sentry_sdk import capture_exception
from social_core.pipeline.partial import partial
from social_django.strategy import DjangoStrategy

from posthog.api.shared import UserBasicSerializer
from posthog.demo.hedgebox import HedgeboxMatrix
from posthog.demo.matrix import MatrixManager
from posthog.event_usage import alias_invite_id, report_user_joined_organization, report_user_signed_up
from posthog.models import Organization, OrganizationDomain, OrganizationInvite, Team, User
from posthog.permissions import CanCreateOrg
from posthog.tasks import user_identify
from posthog.utils import get_can_create_org, mask_email_address

logger = structlog.get_logger(__name__)


class SignupSerializer(serializers.Serializer):
    first_name: serializers.Field = serializers.CharField(max_length=128)
    email: serializers.Field = serializers.EmailField(
        validators=[
            validators.UniqueValidator(
                queryset=User.objects.all(), message="There is already an account with this email address."
            )
        ]
        if not settings.DEMO
        else []  # In the demo environment, we treat an email collision in signup as login
    )
    password: serializers.Field = serializers.CharField(allow_null=True, required=not settings.DEMO)
    organization_name: serializers.Field = serializers.CharField(max_length=128, required=False, allow_blank=True)
    email_opt_in: serializers.Field = serializers.BooleanField(default=True)

    # Slightly hacky: self vars for internal use
    _user: User
    _team: Team
    _organization: Organization

    def validate_password(self, value):
        if value is not None:
            password_validation.validate_password(value)
        return value

    def create(self, validated_data, **kwargs):
        if settings.DEMO:
            return self.enter_demo(validated_data)

        is_instance_first_user: bool = not User.objects.exists()

        organization_name = validated_data.pop("organization_name", validated_data["first_name"])

        self._organization, self._team, self._user = User.objects.bootstrap(
            organization_name=organization_name,
            create_team=self.create_team,
            **validated_data,
            is_staff=is_instance_first_user,
        )
        user = self._user

        login(
            self.context["request"], user, backend="django.contrib.auth.backends.ModelBackend",
        )

        report_user_signed_up(
            user,
            is_instance_first_user=is_instance_first_user,
            is_organization_first_user=True,
            new_onboarding_enabled=(not self._organization.setup_section_2_completed),
            backend_processor="OrganizationSignupSerializer",
            user_analytics_metadata=user.get_analytics_metadata(),
            org_analytics_metadata=user.organization.get_analytics_metadata() if user.organization else None,
        )

        return user

    def enter_demo(self, validated_data) -> User:
        """Demo signup/login flow."""
        email = validated_data["email"]
        first_name = validated_data["first_name"]
        organization_name = validated_data["organization_name"]
        matrix = HedgeboxMatrix(
            start=timezone.datetime.now() - timezone.timedelta(days=120), end=timezone.datetime.now(), n_clusters=50,
        )
        self._organization, self._team, self._user = MatrixManager.ensure_account_and_run(
            matrix, email, first_name, organization_name
        )

        login(
            self.context["request"], self._user, backend="django.contrib.auth.backends.ModelBackend",
        )
        return self._user

    def create_team(self, organization: Organization, user: User) -> Team:
        return Team.objects.create_with_data(user=user, organization=organization)

    def to_representation(self, instance) -> Dict:
        data = UserBasicSerializer(instance=instance).data
        data["redirect_url"] = "/ingestion" if not settings.DEMO else "/"
        return data


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
                user,
                is_instance_first_user=False,
                is_organization_first_user=False,
                new_onboarding_enabled=(not invite.organization.setup_section_2_completed),
                backend_processor="OrganizationInviteSignupSerializer",
                user_analytics_metadata=user.get_analytics_metadata(),
                org_analytics_metadata=user.organization.get_analytics_metadata() if user.organization else None,
            )

        else:
            report_user_joined_organization(organization=invite.organization, current_user=user)

        alias_invite_id(user, str(invite.id))

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


# Social Signup
# views & serializers
class SocialSignupSerializer(serializers.Serializer):
    """
    Signup serializer when the account is created using social authentication.
    Pre-processes information not obtained from SSO provider to create organization.
    """

    organization_name: serializers.Field = serializers.CharField(max_length=128)
    first_name: serializers.Field = serializers.CharField(max_length=128)

    def create(self, validated_data, **kwargs):
        request = self.context["request"]

        if not request.session.get("backend"):
            raise serializers.ValidationError(
                "Inactive social login session. Go to /login and log in before continuing.",
            )

        email = request.session.get("email")
        organization_name = validated_data["organization_name"]
        first_name = validated_data["first_name"]

        serializer = SignupSerializer(
            data={"organization_name": organization_name, "first_name": first_name, "email": email, "password": None,},
            context={"request": request},
        )

        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        logger.info(
            f"social_create_user_signup", full_name_len=len(first_name), email_len=len(email), user=user.id,
        )

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


def process_social_invite_signup(strategy: DjangoStrategy, invite_id: str, email: str, full_name: str) -> User:
    try:
        invite: Union[OrganizationInvite, TeamInviteSurrogate] = OrganizationInvite.objects.select_related(
            "organization",
        ).get(id=invite_id)
    except (OrganizationInvite.DoesNotExist, ValidationError):
        try:
            invite = TeamInviteSurrogate(invite_id)
        except Team.DoesNotExist:
            raise ValidationError("Team does not exist", code="invalid_invite", params={"source": "social_create_user"})

    invite.validate(user=None, email=email)

    try:
        user = strategy.create_user(email=email, first_name=full_name, password=None)
    except Exception as e:
        capture_exception(e)
        message = "Account unable to be created. This account may already exist. Please try again or use different credentials."
        raise ValidationError(message, code="unknown", params={"source": "social_create_user"})

    invite.use(user, prevalidated=True)

    return user


def process_social_domain_jit_provisioning_signup(
    email: str, full_name: str, user: Optional[User] = None
) -> Optional[User]:
    # Check if the user is on a whitelisted domain
    domain = email.split("@")[-1]
    try:
        logger.info(f"process_social_domain_jit_provisioning_signup", domain=domain)
        domain_instance = OrganizationDomain.objects.get(domain=domain)
    except OrganizationDomain.DoesNotExist:
        logger.info(f"process_social_domain_jit_provisioning_signup_domain_does_not_exist", domain=domain)
        return user
    else:
        logger.info(
            f"process_social_domain_jit_provisioning_signup_domain_exists",
            domain=domain,
            is_verified=domain_instance.is_verified,
            jit_provisioning_enabled=domain_instance.jit_provisioning_enabled,
        )
        if domain_instance.is_verified and domain_instance.jit_provisioning_enabled:
            if not user:
                user = User.objects.create_and_join(
                    organization=domain_instance.organization, email=email, password=None, first_name=full_name
                )
                logger.info(
                    f"process_social_domain_jit_provisioning_join_complete",
                    domain=domain,
                    user=user.email,
                    organization=domain_instance.organization.id,
                )
            elif not user.organizations.filter(pk=domain_instance.organization.pk).exists():
                user.join(organization=domain_instance.organization)
                logger.info(
                    f"process_social_domain_jit_provisioning_join_existing",
                    domain=domain,
                    user=user.email,
                    organization=domain_instance.organization.id,
                )

    return user


@partial
def social_create_user(strategy: DjangoStrategy, details, backend, request, user=None, *args, **kwargs):
    if user:
        logger.info(f"social_create_user_is_not_new")
        process_social_domain_jit_provisioning_signup(user.email, user.first_name, user)
        return {"is_new": False}

    backend_processor = "social_create_user"
    email = details["email"][0] if isinstance(details["email"], (list, tuple)) else details["email"]
    full_name = (
        details.get("fullname")
        or f"{details.get('first_name') or ''} {details.get('last_name') or ''}".strip()
        or details.get("username")
    )
    strategy.session_set("user_name", full_name)
    strategy.session_set("backend", backend.name)
    from_invite = False
    invite_id = strategy.session_get("invite_id")

    if not email or not full_name:
        missing_attr = "email" if not email else "name"
        raise ValidationError(
            {missing_attr: "This field is required and was not provided by the IdP."}, code="required"
        )

    logger.info(f"social_create_user", full_name_len=len(full_name), email_len=len(email))

    if invite_id:
        from_invite = True
        user = process_social_invite_signup(strategy, invite_id, email, full_name)

    else:
        # JIT Provisioning?
        user = process_social_domain_jit_provisioning_signup(email, full_name)
        logger.info(
            f"social_create_user_jit_user",
            full_name_len=len(full_name),
            email_len=len(email),
            user=user.id if user else None,
        )
        if user:
            backend_processor = "domain_whitelist"  # This is actually `jit_provisioning` (name kept for backwards-compatibility purposes)

        if not user:
            logger.info(f"social_create_user_jit_failed", full_name_len=len(full_name), email_len=len(email))

            if not get_can_create_org(request.user):
                if email and OrganizationDomain.objects.get_verified_for_email_address(email):
                    # There's a claimed and verified domain for the user's email address domain, but JIT provisioning is not enabled. To avoid confusion
                    # don't let the user create a new org (very likely they won't want this) and show an appropriate error response.
                    return redirect("/login?error_code=jit_not_enabled")
                else:
                    return redirect("/login?error_code=no_new_organizations")
            strategy.session_set("email", email)
            organization_name = strategy.session_get("organization_name")
            query_params = {
                "organization_name": organization_name or "",
                "first_name": full_name or "",
                "email": email or "",
            }
            query_params_string = urlencode(query_params)
            logger.info(
                "social_create_user_confirm_organization", full_name_len=len(full_name), email_len=len(email),
            )

            return redirect(f"/organization/confirm-creation?{query_params_string}",)

    report_user_signed_up(
        user,
        is_instance_first_user=User.objects.count() == 1,
        is_organization_first_user=not from_invite,
        new_onboarding_enabled=False,
        backend_processor=backend_processor,
        social_provider=backend.name,
        user_analytics_metadata=user.get_analytics_metadata(),
        org_analytics_metadata=user.organization.get_analytics_metadata() if user.organization else None,
    )

    return {"is_new": True, "user": user}
