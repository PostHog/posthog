from typing import Any, Dict, Optional, cast

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.http import JsonResponse
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.event_usage import report_user_logged_in
from posthog.models import User


def axess_lockout(*args, **kwargs):
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
        request = self.context["request"]
        user = cast(
            Optional[User], authenticate(request, email=validated_data["email"], password=validated_data["password"])
        )

        if not user:
            raise serializers.ValidationError("Invalid email or password.", code="invalid_credentials")

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        report_user_logged_in(user.distinct_id, social_provider="")
        return user


class LoginViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    queryset = User.objects.none()
    serializer_class = LoginSerializer
    permission_classes = (permissions.AllowAny,)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Method `create()` is overridden to send a more appropriate HTTP status code.
        """
        response = super().create(request, *args, **kwargs)
        response.status_code = status.HTTP_200_OK
        return response
