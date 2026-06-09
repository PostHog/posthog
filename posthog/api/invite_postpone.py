from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

import jwt
import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import permissions, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.constants import INVITE_DAYS_VALIDITY
from posthog.event_usage import groups
from posthog.jwt import PosthogJwtAudience, decode_jwt
from posthog.models.organization_invite import OrganizationInvite

# Recipients can postpone an invite arbitrarily far (validity extends with each postpone), but a
# sane upper bound on a single hop guards against a forged/fat-fingered timestamp parking an invite
# years out.
MAX_POSTPONE_HORIZON_DAYS = 90


class InvitePostponeInfoSerializer(serializers.Serializer):
    organization_name = serializers.CharField(help_text="Name of the organization the invite is for.")
    target_email = serializers.EmailField(
        allow_null=True, help_text="Email address the invite was sent to, shown so the recipient can confirm it."
    )
    inviter_first_name = serializers.CharField(
        allow_blank=True, help_text="First name of the person who sent the invite, if known."
    )
    scheduled_send_at = serializers.DateTimeField(
        allow_null=True, help_text="When the next postponed invite email is currently scheduled, or null if none."
    )
    expires_at = serializers.DateTimeField(help_text="When the invite (and this postpone link) expires.")


class InvitePostponeRequestSerializer(serializers.Serializer):
    token = serializers.CharField(help_text="Signed postpone token from the invite email's 'Do this later' link.")
    send_at = serializers.DateTimeField(
        help_text=(
            "Absolute time (ISO 8601, with timezone) to re-send the invite email. Computed in the "
            "recipient's browser timezone from the chosen option (in an hour, tonight, tomorrow, custom)."
        )
    )
    option = serializers.ChoiceField(
        choices=["hour", "tonight", "tomorrow", "custom"],
        required=False,
        allow_null=True,
        help_text="Which preset the recipient picked (hour/tonight/tomorrow) or 'custom'. Captured for usage analytics only.",
    )

    def validate_send_at(self, value: datetime) -> datetime:
        now = timezone.now()
        if value <= now:
            raise serializers.ValidationError("Pick a time in the future.")
        if value > now + timedelta(days=MAX_POSTPONE_HORIZON_DAYS):
            raise serializers.ValidationError(f"Can't postpone more than {MAX_POSTPONE_HORIZON_DAYS} days from now.")
        return value


class InvitePostponeResultSerializer(serializers.Serializer):
    scheduled_send_at = serializers.DateTimeField(help_text="Confirmed time the next invite email will be sent.")
    expires_at = serializers.DateTimeField(help_text="Updated invite expiry after postponing.")


class InvitePostponeErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Human-readable explanation of why the postpone link can't be used.")
    code = serializers.CharField(help_text="Machine-readable error code: invalid_token or expired.")


def _invite_from_token(token: str) -> OrganizationInvite | None:
    """Resolve the invite a signed postpone token points to, or None if the token is unusable.

    The signature is the authorization: only the email recipient holds a valid token, so the
    cross-organization lookup by id is intentional (mirrors the bare invite UUID accept link).
    """
    if not token:
        return None
    try:
        payload = decode_jwt(token, PosthogJwtAudience.INVITE_POSTPONE)
    except jwt.PyJWTError:
        return None
    invite_id = payload.get("invite_id")
    if not invite_id:
        return None
    try:
        # nosemgrep: idor-lookup-without-org, idor-taint-user-input-to-org-model (signed token is the auth token)
        return OrganizationInvite.objects.select_related("organization", "created_by").filter(id=invite_id).first()
    except (DjangoValidationError, ValueError):
        return None


def _error(detail: str, code: str) -> Response:
    return Response(
        InvitePostponeErrorSerializer({"detail": detail, "code": code}).data,
        status=status.HTTP_400_BAD_REQUEST,
    )


class InvitePostponeView(APIView):
    """Public, token-gated endpoint backing the 'postpone this invite email' page.

    Unauthenticated by design — the recipient clicking the email link has no PostHog account yet.
    The signed JWT in the link is the only credential.
    """

    permission_classes = (permissions.AllowAny,)
    authentication_classes = []

    @extend_schema(
        operation_id="invite_postpone_retrieve",
        parameters=[
            OpenApiParameter(
                name="token",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Signed postpone token from the invite email link.",
            )
        ],
        responses={
            200: InvitePostponeInfoSerializer,
            400: OpenApiResponse(response=InvitePostponeErrorSerializer, description="Invalid or expired token."),
        },
    )
    def get(self, request: Request) -> Response:
        invite = _invite_from_token(request.query_params.get("token", ""))
        if invite is None:
            return _error("This link is invalid or has expired.", "invalid_token")
        if invite.is_expired():
            return _error("This invite has expired. Please ask your admin for a new one.", "expired")
        return Response(
            InvitePostponeInfoSerializer(
                {
                    "organization_name": invite.organization.name,
                    "target_email": invite.target_email,
                    "inviter_first_name": invite.created_by.first_name if invite.created_by else "",
                    "scheduled_send_at": invite.scheduled_send_at,
                    "expires_at": invite.effective_expires_at(),
                }
            ).data
        )

    @extend_schema(
        operation_id="invite_postpone_create",
        request=InvitePostponeRequestSerializer,
        responses={
            200: InvitePostponeResultSerializer,
            400: OpenApiResponse(
                response=InvitePostponeErrorSerializer, description="Invalid or expired token, or bad send_at."
            ),
        },
    )
    def post(self, request: Request) -> Response:
        request_serializer = InvitePostponeRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        send_at = request_serializer.validated_data["send_at"]
        option = request_serializer.validated_data.get("option")

        invite = _invite_from_token(request_serializer.validated_data["token"])
        if invite is None:
            return _error("This link is invalid or has expired.", "invalid_token")
        if invite.is_expired():
            return _error("This invite has expired. Please ask your admin for a new one.", "expired")

        now = timezone.now()
        # Dev convenience: collapse every postpone to ~1 minute out so a rescheduled invite comes
        # back almost immediately while testing, instead of waiting hours/days for the chosen time.
        if settings.DEBUG:
            send_at = now + timedelta(minutes=1)
        # Extend validity so the rescheduled email's accept link is still good when it lands.
        new_expiry = send_at + timedelta(days=INVITE_DAYS_VALIDITY)
        # Bypass save()/activity logging: this is an unauthenticated, system-level write with no user.
        # invite was resolved from the signed token (the authorization), so pk=invite.pk targets only
        # that already-authorized invite, not arbitrary user input.
        # nosemgrep: idor-taint-user-input-to-org-model
        OrganizationInvite.objects.filter(pk=invite.pk).update(
            scheduled_send_at=send_at,
            expires_at=new_expiry,
            updated_at=now,
        )

        # Track usage. distinct_id mirrors send_invite's recipient id so these events tie to the
        # same person once the invite is accepted (the invite_<id> alias becomes the user).
        posthoganalytics.capture(
            distinct_id=f"invite_{invite.id}",
            event="organization invite postponed",
            properties={
                "invite_id": str(invite.id),
                "option": option,
                # How many times this invite's email had already been re-sent before this postpone.
                "prior_postpone_count": invite.postpone_count,
                "hours_until_resend": round((send_at - now).total_seconds() / 3600, 1),
            },
            groups=groups(invite.organization),
        )
        return Response(InvitePostponeResultSerializer({"scheduled_send_at": send_at, "expires_at": new_expiry}).data)
