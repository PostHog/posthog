"""Personal Settings → Personal integrations: manage the user's verified SMS phone number.

A ``UserIntegration`` (kind=sms) stores the user's verified phone number in
``integration_id`` (E.164 format). The verification flow is two steps:

1. ``POST /api/users/@me/sms/start_verification`` → SendBlue sends a 6-digit code,
   we cache ``(phone, code, expires_at)`` keyed by the user.
2. ``POST /api/users/@me/sms/verify`` → if the submitted code matches and hasn't
   expired we create the ``UserIntegration`` row.

The same phone number cannot be claimed by two PostHog users — a partial unique
constraint on ``UserIntegration(kind="sms", integration_id)`` enforces this at
the database level.
"""

import re
import secrets
from typing import cast

from django.core.cache import cache
from django.db import IntegrityError

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.clients.sendblue import SendBlueError, SendBlueNotConfigured, get_sendblue_client
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.permissions import APIScopePermission

logger = structlog.get_logger(__name__)

SMS_VERIFICATION_CACHE_PREFIX = "user_sms_verify:"
SMS_VERIFICATION_TTL_SECONDS = 600  # 10 minutes
SMS_VERIFICATION_CODE_LENGTH = 6

# Conservative E.164: leading +, 8-15 digits, no leading zero on the country code.
E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


def _normalize_phone(raw: str) -> str:
    cleaned = re.sub(r"[\s\-()]", "", raw or "")
    if not E164_PATTERN.match(cleaned):
        raise exceptions.ValidationError("Phone number must be in E.164 format (e.g. +14155552671).")
    return cleaned


def _verification_cache_key(user: User) -> str:
    return f"{SMS_VERIFICATION_CACHE_PREFIX}{user.pk}"


class SMSIntegrationItemSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="PostHog UserIntegration row id.")
    phone_number = serializers.CharField(help_text="Verified phone number in E.164 format.")
    created_at = serializers.DateTimeField(help_text="When the phone number was verified.")


class SMSStartVerificationRequestSerializer(serializers.Serializer):
    phone_number = serializers.CharField(
        help_text="Phone number to verify, in E.164 format (e.g. +14155552671).",
    )


class SMSStartVerificationResponseSerializer(serializers.Serializer):
    phone_number = serializers.CharField(help_text="Normalized phone number the verification code was sent to.")
    expires_in_seconds = serializers.IntegerField(help_text="Seconds until the verification code expires.")


class SMSVerifyRequestSerializer(serializers.Serializer):
    phone_number = serializers.CharField(help_text="Phone number being verified, in E.164 format.")
    code = serializers.CharField(help_text=f"{SMS_VERIFICATION_CODE_LENGTH}-digit verification code received via SMS.")


def _serialize_sms_integration(integration: UserIntegration) -> dict:
    return {
        "id": str(integration.id),
        "phone_number": integration.integration_id,
        "created_at": integration.created_at,
    }


@extend_schema(tags=["core"])
class UserSMSIntegrationViewSet(viewsets.GenericViewSet):
    """`/api/users/@me/sms/` — manage the user's verified phone number for SMS."""

    scope_object = "user"
    required_scopes: list[str] | None = None
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["destroy", "start_verification", "verify"]

    authentication_classes = [OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    http_method_names = ["get", "post", "delete"]
    serializer_class = SMSIntegrationItemSerializer
    pagination_class = None

    def _get_user(self) -> User:
        request_user = cast(User, self.request.user)
        uuid_param = self.kwargs.get("parent_lookup_uuid")
        if uuid_param is None or uuid_param == "@me":
            return request_user
        if not request_user.is_staff:
            raise exceptions.PermissionDenied(
                "As a non-staff user you're only allowed to access the `@me` user instance."
            )
        user = User.objects.filter(uuid=uuid_param, is_active=True).first()
        if user is None:
            raise exceptions.NotFound()
        return user

    @extend_schema(
        summary="List verified phone numbers",
        responses={200: SMSIntegrationItemSerializer(many=True)},
    )
    def list(self, request: Request, **_kwargs) -> Response:
        user = self._get_user()
        integrations = UserIntegration.objects.filter(user=user, kind=UserIntegration.IntegrationKind.SMS).order_by(
            "created_at"
        )
        return Response([_serialize_sms_integration(i) for i in integrations])

    @extend_schema(
        summary="Disconnect a verified phone number",
        responses={204: OpenApiResponse(description="Phone number removed.")},
    )
    @action(methods=["DELETE"], detail=False, url_path=r"(?P<phone>\+[0-9]+)")
    def destroy_phone(self, request: Request, phone: str, **_kwargs) -> Response:
        user = self._get_user()
        integration = UserIntegration.objects.filter(
            user=user, kind=UserIntegration.IntegrationKind.SMS, integration_id=phone
        ).first()
        if integration is None:
            raise exceptions.NotFound("No verified phone number matches.")
        integration.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Send an SMS verification code",
        request=SMSStartVerificationRequestSerializer,
        responses={200: SMSStartVerificationResponseSerializer},
    )
    @action(methods=["POST"], detail=False, url_path="start_verification")
    def start_verification(self, request: Request, **_kwargs) -> Response:
        user = self._get_user()
        body = SMSStartVerificationRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        phone = _normalize_phone(body.validated_data["phone_number"])

        if (
            UserIntegration.objects.filter(kind=UserIntegration.IntegrationKind.SMS, integration_id=phone)
            .exclude(user=user)
            .exists()
        ):
            raise exceptions.ValidationError("This phone number is already linked to another PostHog account.")

        try:
            client = get_sendblue_client()
        except SendBlueNotConfigured:
            raise exceptions.ValidationError("SMS integration is not configured on this PostHog instance.")

        code = "".join(secrets.choice("0123456789") for _ in range(SMS_VERIFICATION_CODE_LENGTH))
        cache.set(
            _verification_cache_key(user),
            {"phone": phone, "code": code},
            timeout=SMS_VERIFICATION_TTL_SECONDS,
        )

        try:
            client.send_message(to=phone, body=f"Your PostHog verification code is {code}")
        except SendBlueError as exc:
            logger.warning("user_sms.start_verification.send_failed", user_id=user.pk, error=str(exc))
            raise exceptions.ValidationError("Could not send the verification code. Try again in a moment.")

        return Response(
            {"phone_number": phone, "expires_in_seconds": SMS_VERIFICATION_TTL_SECONDS},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Verify an SMS verification code",
        request=SMSVerifyRequestSerializer,
        responses={201: SMSIntegrationItemSerializer},
    )
    @action(methods=["POST"], detail=False, url_path="verify")
    def verify(self, request: Request, **_kwargs) -> Response:
        user = self._get_user()
        body = SMSVerifyRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        phone = _normalize_phone(body.validated_data["phone_number"])
        submitted_code = body.validated_data["code"].strip()

        cache_key = _verification_cache_key(user)
        cached = cache.get(cache_key)
        if not cached or cached.get("phone") != phone:
            raise exceptions.ValidationError("No active verification for this phone number. Request a new code.")
        if not secrets.compare_digest(str(cached.get("code", "")), submitted_code):
            raise exceptions.ValidationError("Invalid verification code.")

        cache.delete(cache_key)

        try:
            integration, _ = UserIntegration.objects.update_or_create(
                user=user,
                kind=UserIntegration.IntegrationKind.SMS,
                integration_id=phone,
                defaults={"config": {}, "sensitive_config": {}},
            )
        except IntegrityError:
            raise exceptions.ValidationError("This phone number is already linked to another PostHog account.")

        return Response(_serialize_sms_integration(integration), status=status.HTTP_201_CREATED)
