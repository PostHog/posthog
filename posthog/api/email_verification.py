from typing import Any

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.tokens import default_token_generator
from django.utils import timezone
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.authentication import NonCreatingViewSetMixin
from posthog.email import is_email_available
from posthog.event_usage import report_user_logged_in, report_user_verified_email
from posthog.models import User
from posthog.tasks.email import send_email_change_emails, send_email_verification


class VerifyEmailSerializer(serializers.Serializer):
    token = serializers.CharField(write_only=True)


class VerifyEmailViewSet(NonCreatingViewSetMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = User.objects.none()
    serializer_class = VerifyEmailSerializer
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
            user: User = User.objects.filter(is_active=True).get(uuid=user_uuid)
        except User.DoesNotExist:
            user = None

        if not user or not default_token_generator.check_token(user, token):
            raise serializers.ValidationError(
                {"token": ["This verification token is invalid or has expired."]}, code="invalid_token"
            )

        if user.pending_email:
            old_email = user.email
            user.email = user.pending_email
            user.pending_email = None
            user.save()
            send_email_change_emails.delay(timezone.now().isoformat(), user.first_name, old_email, user.email)

        user.is_email_verified = True
        user.save()
        report_user_verified_email(user)

        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")
        report_user_logged_in(user)
        return {"success": True, "token": token}

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        response = super().retrieve(request, *args, **kwargs)
        response.status_code = self.SUCCESS_STATUS_CODE
        return response


class RequestVerifyEmailSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(write_only=True)

    def create(self, validated_data):
        uuid = validated_data.pop("uuid")

        if not is_email_available():
            raise serializers.ValidationError(
                "Cannot verify email address because email is not configured for your instance. Please contact your administrator.",
                code="email_not_available",
            )

        try:
            user = User.objects.filter(is_active=True).get(uuid=uuid)
        except User.DoesNotExist:
            user = None

        if user:
            send_email_verification(user.id)

        # TODO: Limit number of requests for verification emails

        return True


class RequestVerifyEmailViewSet(NonCreatingViewSetMixin, viewsets.GenericViewSet):
    queryset = User.objects.none()
    serializer_class = RequestVerifyEmailSerializer
    permission_classes = (permissions.AllowAny,)
    SUCCESS_STATUS_CODE = status.HTTP_204_NO_CONTENT
