from typing import cast

from rest_framework import exceptions, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.enums import LabeledStrEnum
from posthog.event_usage import report_user_action
from posthog.models.integration.claude_subscription import (
    MAX_TOKEN_LENGTH,
    ClaudeSubscriptionStore,
    ClaudeSubscriptionSummary,
    InvalidClaudeSubscriptionToken,
    claude_subscription_storage_enabled,
)
from posthog.models.user import User
from posthog.oauth_provenance import is_sandbox_origin_request

from products.cloud_agents.backend.facade.access import cloud_agents_enabled


class ClaudeSubscriptionStatus(LabeledStrEnum):
    CONNECTED = "connected"
    NOT_CONNECTED = "not_connected"


class UserClaudeSubscriptionConnectRequestSerializer(serializers.Serializer):
    token = serializers.CharField(
        write_only=True,
        max_length=MAX_TOKEN_LENGTH,
        style={"input_type": "password"},
        help_text=(
            "The token that `claude setup-token` prints. It starts with `sk-ant-oat`. PostHog stores it encrypted, "
            "and no response returns it. A new token replaces the stored one."
        ),
    )


class UserClaudeSubscriptionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=ClaudeSubscriptionStatus.choices,
        help_text="`connected` when a token is stored for cloud agent runs; `not_connected` when none is stored.",
    )
    token_suffix = serializers.CharField(
        allow_null=True,
        help_text="The last 4 characters of the stored token, so the user can tell which token it is.",
    )
    connected_at = serializers.DateTimeField(allow_null=True, help_text="When the token was stored.")
    last_used_at = serializers.DateTimeField(
        allow_null=True, help_text="When a cloud agent run last used the token. Null when no run has used it."
    )


def serialize_claude_subscription(summary: ClaudeSubscriptionSummary | None) -> dict[str, object]:
    if summary is None:
        return {
            "status": ClaudeSubscriptionStatus.NOT_CONNECTED,
            "token_suffix": None,
            "connected_at": None,
            "last_used_at": None,
        }
    return dict(
        UserClaudeSubscriptionSerializer(
            {
                "status": ClaudeSubscriptionStatus.CONNECTED,
                "token_suffix": summary.token_suffix,
                "connected_at": summary.connected_at,
                "last_used_at": summary.last_used_at,
            }
        ).data
    )


def ensure_not_sandbox_claude_subscription_request(request: Request) -> None:
    if is_sandbox_origin_request(request):
        raise exceptions.PermissionDenied("Cloud agent runs cannot read or change the stored Claude subscription.")


def get_own_user(request: Request, user_uuid: str | None) -> User:
    """The requesting user. Unlike the other personal integrations, staff cannot name another user here."""
    user = cast(User, request.user)
    if user_uuid not in (None, "@me", str(user.uuid)):
        raise exceptions.PermissionDenied("You can only manage your own Claude subscription.")
    return user


def ensure_claude_subscription_connect_enabled(user: User) -> None:
    organization_id = str(user.current_organization_id)
    if not cloud_agents_enabled(str(user.distinct_id), organization_id) or not claude_subscription_storage_enabled(
        user
    ):
        raise exceptions.NotFound()


def get_claude_subscription(user: User) -> Response:
    return Response(serialize_claude_subscription(ClaudeSubscriptionStore.for_user(user.id)))


def connect_claude_subscription(user: User, token: str) -> Response:
    try:
        summary = ClaudeSubscriptionStore.connect(user.id, token)
    except InvalidClaudeSubscriptionToken as error:
        report_user_action(user, "claude subscription connect failed", {"reason": "invalid"})
        raise exceptions.ValidationError({"token": str(error)})
    report_user_action(user, "claude subscription connected", {})
    return Response(serialize_claude_subscription(summary))


def disconnect_claude_subscription(user: User) -> Response:
    if ClaudeSubscriptionStore.disconnect(user.id):
        report_user_action(user, "claude subscription disconnected", {})
    return Response(status=status.HTTP_204_NO_CONTENT)
