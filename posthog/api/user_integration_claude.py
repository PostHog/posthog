import posthoganalytics
from rest_framework import exceptions, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models.integration.claude import (
    STATUS_NOT_CONNECTED,
    ClaudeAuthError,
    ClaudeIntegrationStatus,
    ClaudeUserIntegration,
    parse_claude_setup_token,
)
from posthog.models.user import User
from posthog.oauth_provenance import is_sandbox_oauth_request

from products.tasks.backend.facade.api import CLAUDE_OWN_SUBSCRIPTION_CLOUD_FEATURE_FLAG


class UserClaudeConnectRequestSerializer(serializers.Serializer):
    token = serializers.CharField(
        write_only=True,
        trim_whitespace=True,
        help_text=(
            "The long-lived OAuth token that `claude setup-token` prints. It starts with `sk-ant-oat01-`. PostHog "
            "stores it encrypted and gives it only to the user's own Claude cloud runs."
        ),
    )


class UserClaudeIntegrationSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=ClaudeIntegrationStatus.choices,
        help_text=(
            "`connected` when cloud runs can use the token; `reauth_required` when Anthropic rejected the token and "
            "the user must paste a new one; `not_connected` when no token is stored."
        ),
    )
    connected_at = serializers.DateTimeField(required=False, allow_null=True, help_text="When the token was connected.")


def serialize_claude_integration(integration: ClaudeUserIntegration | None) -> dict[str, str | None]:
    if integration is None:
        return {"status": STATUS_NOT_CONNECTED, "connected_at": None}
    return {"status": integration.status, "connected_at": integration.connected_at}


def ensure_not_sandbox_claude_request(request: Request) -> None:
    if is_sandbox_oauth_request(request):
        raise exceptions.PermissionDenied("Cloud tasks cannot change the connected Claude token.")


def ensure_claude_connect_enabled(user: User) -> None:
    organization_id = str(user.current_organization_id)
    try:
        enabled = posthoganalytics.feature_enabled(
            CLAUDE_OWN_SUBSCRIPTION_CLOUD_FEATURE_FLAG,
            str(user.distinct_id),
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception as error:
        capture_exception(error)
        enabled = False
    if not enabled:
        raise exceptions.NotFound()


def get_claude_integration(user: User) -> dict[str, str | None]:
    return serialize_claude_integration(ClaudeUserIntegration.for_user(user.id))


def connect_claude_integration(user: User, data: dict[str, str]) -> Response:
    try:
        token = parse_claude_setup_token(data.get("token"))
    except ClaudeAuthError as error:
        report_user_action(user, "claude subscription connect failed", {"reason": "invalid_format"})
        raise exceptions.ValidationError({"token": str(error)})
    integration = ClaudeUserIntegration.connect(user.id, token)
    report_user_action(user, "claude subscription connected", {})
    return Response(serialize_claude_integration(integration))


def disconnect_claude_integration(user: User) -> Response:
    integration = ClaudeUserIntegration.for_user(user.id)
    if integration is not None:
        integration.disconnect()
        report_user_action(user, "claude subscription disconnected", {})
    return Response(status=status.HTTP_204_NO_CONTENT)
