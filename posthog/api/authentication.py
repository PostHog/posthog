from typing import Any, Dict, Optional, cast

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib.auth import views as auth_views
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from loginas.utils import is_impersonated_session, restore_original_login
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from social_django.views import auth

from posthog.email import EmailMessage, is_email_available
from posthog.event_usage import report_user_logged_in, report_user_password_reset
from posthog.models import OrganizationDomain, User
from posthog.utils import get_instance_available_sso_providers


@csrf_protect
def logout(request):
    if request.user.is_authenticated:
        request.user.temporary_token = None
        request.user.save()

    if is_impersonated_session(request):
        restore_original_login(request)
        return redirect("/admin/")

    response = auth_views.logout_then_login(request)
    return response


def axes_locked_out(*args, **kwargs):
    return JsonResponse(
        {
            "type": "authentication_error",
            "code": "too_many_failed_attempts",
            "detail": "Too many failed login attempts. Please try again in"
            f" {int(settings.AXES_COOLOFF_TIME.seconds / 60)} minutes.",
            "attr": None,
        },
        status=status.HTTP_403_FORBIDDEN,
    )


def sso_login(request: HttpRequest, backend: str) -> HttpResponse:
    sso_providers = get_instance_available_sso_providers()
    # because SAML is configured at the domain-level, we have to assume it's enabled for someone in the instance
    sso_providers["saml"] = settings.EE_AVAILABLE

    if backend not in sso_providers:
        return redirect(f"/login?error_code=invalid_sso_provider")

    if not sso_providers[backend]:
        return redirect(f"/login?error_code=improperly_configured_sso")

    return auth(request, backend)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()

    def to_representation(self, instance: Any) -> Dict[str, Any]:
        return {"success": True}

    def create(self, validated_data: Dict[str, str]) -> Any:

        # Check SSO enforcement (which happens at the domain level)
        sso_enforcement = OrganizationDomain.objects.get_sso_enforcement_for_email_address(validated_data["email"])
        if sso_enforcement:
            raise serializers.ValidationError(
                f"You can only login with SSO for this account ({sso_enforcement}).", code="sso_enforced"
            )

        request = self.context["request"]
        user = cast(
            Optional[User], authenticate(request, email=validated_data["email"], password=validated_data["password"])
        )

        if not user:
            raise serializers.ValidationError("Invalid email or password.", code="invalid_credentials")

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        report_user_logged_in(user, social_provider="")
        return user


class LoginPrecheckSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def to_representation(self, instance: Dict[str, str]) -> Dict[str, Any]:
        return instance

    def create(self, validated_data: Dict[str, str]) -> Any:
        email = validated_data.get("email", "")
        # TODO: Refactor methods below to remove duplicate queries
        return {
            "sso_enforcement": OrganizationDomain.objects.get_sso_enforcement_for_email_address(email),
            "saml_available": OrganizationDomain.objects.get_is_saml_available_for_email(email),
        }


class NonCreatingViewSetMixin(mixins.CreateModelMixin):
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
            Method `create()` is overridden to send a more appropriate HTTP
            status code (as no object is actually created).
            """
        response = super().create(request, *args, **kwargs)
        response.status_code = getattr(self, "SUCCESS_STATUS_CODE", status.HTTP_200_OK)
        return response


class LoginViewSet(NonCreatingViewSetMixin, viewsets.GenericViewSet):
    queryset = User.objects.none()
    serializer_class = LoginSerializer
    permission_classes = (permissions.AllowAny,)


class LoginPrecheckViewSet(NonCreatingViewSetMixin, viewsets.GenericViewSet):
    queryset = User.objects.none()
    serializer_class = LoginPrecheckSerializer
    permission_classes = (permissions.AllowAny,)


class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField(write_only=True)

    def create(self, validated_data):
        email = validated_data.pop("email")

        # Check SSO enforcement (which happens at the domain level)
        if OrganizationDomain.objects.get_sso_enforcement_for_email_address(email):
            raise serializers.ValidationError(
                "Password reset is disabled because SSO login is enforced for this domain.", code="sso_enforced"
            )

        if not is_email_available():
            raise serializers.ValidationError(
                "Cannot reset passwords because email is not configured for your instance. Please contact your administrator.",
                code="email_not_available",
            )

        try:
            user = User.objects.filter(is_active=True).get(email=email)
        except User.DoesNotExist:
            user = None

        if user:
            token = default_token_generator.make_token(user)

            message = EmailMessage(
                campaign_key=f"password-reset-{user.uuid}-{timezone.now()}",
                subject=f"Reset your PostHog password",
                template_name="password_reset",
                template_context={
                    "preheader": "Please follow the link inside to reset your password.",
                    "link": f"/reset/{user.uuid}/{token}",
                    "cloud": settings.MULTI_TENANCY,
                    "site_url": settings.SITE_URL,
                    "social_providers": list(user.social_auth.values_list("provider", flat=True)),
                },
            )
            message.add_recipient(email)
            message.send()

        # TODO: Limit number of requests for password reset emails

        return True


class PasswordResetCompleteSerializer(serializers.Serializer):
    token = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)

    def create(self, validated_data):
        # Special handling for E2E tests (note we don't actually change anything in the DB, just simulate the response)
        if settings.E2E_TESTING and validated_data["token"] == "e2e_test_token":
            return True

        try:
            user = User.objects.filter(is_active=True).get(uuid=self.context["view"].kwargs["user_uuid"])
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {"token": ["This reset token is invalid or has expired."]}, code="invalid_token"
            )

        if not default_token_generator.check_token(user, validated_data["token"]):
            raise serializers.ValidationError(
                {"token": ["This reset token is invalid or has expired."]}, code="invalid_token"
            )

        password = validated_data["password"]
        try:
            validate_password(password, user)
        except ValidationError as e:
            raise serializers.ValidationError({"password": e.messages})

        user.set_password(password)
        user.save()

        login(self.context["request"], user, backend="django.contrib.auth.backends.ModelBackend")
        report_user_password_reset(user)
        return True


class PasswordResetViewSet(NonCreatingViewSetMixin, viewsets.GenericViewSet):
    queryset = User.objects.none()
    serializer_class = PasswordResetSerializer
    permission_classes = (permissions.AllowAny,)
    SUCCESS_STATUS_CODE = status.HTTP_204_NO_CONTENT


class PasswordResetCompleteViewSet(NonCreatingViewSetMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = User.objects.none()
    serializer_class = PasswordResetCompleteSerializer
    permission_classes = (permissions.AllowAny,)
    SUCCESS_STATUS_CODE = status.HTTP_204_NO_CONTENT

    def get_object(self):

        token = self.request.query_params.get("token")
        user_uuid = self.kwargs.get("user_uuid")

        if not token:
            raise serializers.ValidationError({"token": ["This field is required."]}, code="required")

        # Special handling for E2E tests
        if settings.E2E_TESTING and user_uuid == "e2e_test_user" and token == "e2e_test_token":
            return {"success": True, "token": token}

        try:
            user = User.objects.filter(is_active=True).get(uuid=user_uuid)
        except User.DoesNotExist:
            user = None

        if not user or not default_token_generator.check_token(user, token):
            raise serializers.ValidationError(
                {"token": ["This reset token is invalid or has expired."]}, code="invalid_token"
            )

        return {"success": True, "token": token}

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        response = super().retrieve(request, *args, **kwargs)
        response.status_code = self.SUCCESS_STATUS_CODE
        return response
