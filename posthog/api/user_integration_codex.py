import posthoganalytics
from rest_framework import exceptions, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models.integration.codex import (
    STATUS_NOT_CONNECTED,
    CodexAuthError,
    CodexIntegrationStatus,
    CodexReauthRequired,
    CodexUserIntegration,
    parse_codex_auth_json,
)
from posthog.models.user import User
from posthog.oauth_provenance import is_sandbox_oauth_request

from products.tasks.backend.facade.api import CODEX_OWN_SUBSCRIPTION_CLOUD_FEATURE_FLAG


class UserCodexAuthTokensSerializer(serializers.Serializer):
    access_token = serializers.CharField(
        write_only=True, help_text="The ChatGPT access token (a JWT) from the `tokens` object of the Codex `auth.json`."
    )
    refresh_token = serializers.CharField(
        write_only=True, help_text="The single-use ChatGPT refresh token from the same `tokens` object."
    )
    id_token = serializers.CharField(
        write_only=True,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="The OpenID id token from the same `tokens` object, when present. Used to read the account email.",
    )


class UserCodexConnectRequestSerializer(serializers.Serializer):
    tokens = UserCodexAuthTokensSerializer(
        help_text=(
            "The `tokens` object of the `auth.json` that `codex login` wrote. PostHog refreshes the chain once, "
            "stores the rotated tokens, and refreshes them for cloud runs from then on."
        )
    )


class UserCodexIntegrationSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=CodexIntegrationStatus.choices,
        help_text=(
            "`connected` when cloud runs can use the account; `reauth_required` when OpenAI rejected the refresh "
            "token and the user must log in and connect again; `not_connected` when no account is connected."
        ),
    )
    plan_type = serializers.CharField(
        required=False, allow_null=True, help_text="The ChatGPT plan type OpenAI reports for the account."
    )
    email = serializers.EmailField(
        required=False, allow_null=True, help_text="The email of the connected ChatGPT account."
    )
    connected_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="When the account was connected."
    )


class OpenAIUnavailable(exceptions.APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "openai_unavailable"


def serialize_codex_integration(integration: CodexUserIntegration | None) -> dict[str, str | None]:
    if integration is None:
        return {"status": STATUS_NOT_CONNECTED, "plan_type": None, "email": None, "connected_at": None}
    return {
        "status": integration.status,
        "plan_type": integration.plan_type,
        "email": integration.email,
        "connected_at": integration.connected_at,
    }


def ensure_not_sandbox_request(request: Request) -> None:
    if is_sandbox_oauth_request(request):
        raise exceptions.PermissionDenied("Cloud tasks cannot change the connected ChatGPT account.")


def ensure_codex_connect_enabled(user: User) -> None:
    organization_id = str(user.current_organization_id)
    try:
        enabled = posthoganalytics.feature_enabled(
            CODEX_OWN_SUBSCRIPTION_CLOUD_FEATURE_FLAG,
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


def get_codex_integration(user: User) -> dict[str, str | None]:
    return serialize_codex_integration(CodexUserIntegration.for_user(user.id))


def connect_codex_integration(user: User, data: object) -> Response:
    try:
        tokens = parse_codex_auth_json(data)
    except CodexAuthError as error:
        raise exceptions.ValidationError({"tokens": str(error)})
    try:
        integration = CodexUserIntegration.connect(user.id, tokens, source="user_integration_api")
    except CodexReauthRequired as error:
        report_user_action(user, "codex subscription connect failed", {"reason": "rejected_by_openai"})
        raise exceptions.ValidationError({"tokens": str(error)})
    except CodexAuthError as error:
        report_user_action(user, "codex subscription connect failed", {"reason": "openai_unreachable"})
        capture_exception(error)
        raise OpenAIUnavailable(str(error))
    report_user_action(user, "codex subscription connected", {"plan_type": integration.plan_type})
    return Response(serialize_codex_integration(integration))


def disconnect_codex_integration(user: User) -> Response:
    integration = CodexUserIntegration.for_user(user.id)
    if integration is not None:
        integration.disconnect(source="user_integration_api")
        report_user_action(user, "codex subscription disconnected", {})
    return Response(status=status.HTTP_204_NO_CONTENT)
