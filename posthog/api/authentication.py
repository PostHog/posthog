from typing import Any, Dict, Optional, cast

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib.auth import views as auth_views
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from loginas.utils import is_impersonated_session, restore_original_login
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.email import EmailMessage, is_email_available
from posthog.event_usage import report_user_logged_in, report_user_password_reset
from posthog.models import User


@csrf_protect
def logout(request):
    if request.user.is_authenticated:
        request.user.temporary_token = None
        request.user.save()

    if is_impersonated_session(request):
        restore_original_login(request)
        return redirect("/admin/")

    response = auth_views.logout_then_login(request)
    response.delete_cookie(settings.TOOLBAR_COOKIE_NAME, "/")

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


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()

    def to_representation(self, instance: Any) -> Dict[str, Any]:
        return {"success": True}

    def create(self, validated_data: Dict[str, str]) -> Any:
        if getattr(settings, "SAML_ENFORCED", False):
            raise serializers.ValidationError("This instance only allows SAML login.", code="saml_enforced")

        request = self.context["request"]
        user = cast(
            Optional[User], authenticate(request, email=validated_data["email"], password=validated_data["password"])
        )

        if not user:
            raise serializers.ValidationError("Invalid email or password.", code="invalid_credentials")

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        report_user_logged_in(user, social_provider="")
        return user


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


class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField(write_only=True)

    def create(self, validated_data):

        if getattr(settings, "SAML_ENFORCED", False):
            raise serializers.ValidationError(
                "Password reset is disabled because SAML login is enforced.", code="saml_enforced"
            )

        if not is_email_available():
            raise serializers.ValidationError(
                "Cannot reset passwords because email is not configured for your instance. Please contact your administrator.",
                code="email_not_available",
            )

        email = validated_data.pop("email")
        try:
            user = User.objects.get(email=email)
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
            user = User.objects.get(uuid=self.context["view"].kwargs["user_uuid"])
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
            user = User.objects.get(uuid=user_uuid)
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
