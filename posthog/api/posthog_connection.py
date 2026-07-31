"""Forward arbitrary API requests to another PostHog project through a `posthog` connection.

A `posthog` integration (see `posthog.models.integration`) holds a user-consented, refreshable OAuth
grant against another PostHog project, in another region or your own. This viewset lets the connecting
user replay any request against that project's API — the server injects the stored token, so the
caller (a browser, an agent sandbox, an MCP tool) never holds it.

What the connection can do is bounded three ways: the scopes the user granted at consent, the target
cell's OAuthApplication.allowed_scopes, and the target's normal per-request permission checks. This
side only resolves the token and forwards; it does not re-implement or gate individual endpoints.
"""

import re
from typing import Any

import requests
import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models.integration import POSTHOG_CONNECT_KIND, Integration, OauthIntegration, posthog_connect_base_url

logger = structlog.get_logger(__name__)

CONNECTION_FORWARD_TIMEOUT_SECONDS = 30
_METHODS_WITH_BODY = ("POST", "PUT", "PATCH", "DELETE")
_ALLOWED_METHODS = ("GET", *_METHODS_WITH_BODY)
# A relative API path on the target, e.g. `api/projects/2/insights/`. The host comes from the fixed
# per-region base URL (never from here), so the netloc can't be changed; this just keeps the path a
# well-formed relative path and blocks obvious traversal.
_SAFE_PATH = re.compile(r"^[A-Za-z0-9._~!$&'()*+,;=:@%/-]+$")


def _connection_access_token(integration: Integration) -> str:
    oauth = OauthIntegration(integration)
    if oauth.access_token_expired():
        oauth.refresh_access_token()
        integration.refresh_from_db()
    token = integration.sensitive_config.get("access_token")
    if not token:
        raise ValidationError("This PostHog connection has no usable access token — reconnect it.")
    return token


def _validate_target_path(path: str) -> str:
    stripped = (path or "").lstrip("/")
    if not stripped or "://" in stripped or ".." in stripped or not _SAFE_PATH.match(stripped):
        raise ValidationError("path must be a relative target API path, e.g. `api/projects/2/insights/`.")
    return stripped


class PostHogConnectionForwardSerializer(serializers.Serializer):
    method = serializers.ChoiceField(
        choices=list(_ALLOWED_METHODS), help_text="HTTP method to use against the target project's API."
    )
    path = serializers.CharField(
        help_text="Relative target API path with no host or scheme, e.g. `api/projects/2/insights/`."
    )
    query = serializers.DictField(
        required=False, child=serializers.CharField(), help_text="Query parameters to send to the target."
    )
    data = serializers.JSONField(required=False, help_text="JSON request body for write methods.")


class PostHogConnectionForwardResponseSerializer(serializers.Serializer):
    status = serializers.IntegerField(help_text="HTTP status the target project returned.")
    data = serializers.JSONField(help_text="The target project's response body, passed through.")


class PostHogConnectionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Replay requests against another PostHog project via a `posthog` connection you created."""

    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    scope_object = "integration"
    serializer_class = PostHogConnectionForwardSerializer

    def _get_connection(self, pk: str) -> Integration:
        try:
            integration = Integration.objects.get(team_id=self.team_id, id=pk, kind=POSTHOG_CONNECT_KIND)
        except (Integration.DoesNotExist, ValueError, ValidationError):
            raise NotFound("No PostHog connection with that id in this project.")
        # A connection acts as the user who consented to it. Restrict use to that user so a broad,
        # any-scope grant can't become a team-wide confused deputy in the target project.
        if integration.created_by_id != getattr(self.request.user, "id", None):
            raise PermissionDenied("You can only use a PostHog connection you created.")
        return integration

    @extend_schema(
        request=PostHogConnectionForwardSerializer,
        responses={200: OpenApiResponse(response=PostHogConnectionForwardResponseSerializer)},
        summary="Forward a request through a PostHog connection",
        description="Replay an API request against the connected PostHog project. The server injects the connection's token; the response is passed through.",
    )
    @action(detail=True, methods=["post"], url_path="forward", required_scopes=["integration:write"])
    def forward(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        integration = self._get_connection(pk)
        serializer = PostHogConnectionForwardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        method = payload["method"]
        path = _validate_target_path(payload["path"])
        token = _connection_access_token(integration)
        base = posthog_connect_base_url(integration.config.get("region"))

        try:
            res = requests.request(
                method,
                f"{base}/{path}",
                params=payload.get("query") or None,
                json=payload.get("data") if method in _METHODS_WITH_BODY else None,
                headers={"Authorization": f"Bearer {token}", "X-PostHog-Connection": "1"},
                timeout=CONNECTION_FORWARD_TIMEOUT_SECONDS,
                # A compromised/misconfigured target must not be able to 30x us into resending the
                # bearer token to another origin.
                allow_redirects=False,
            )
        except requests.RequestException as err:
            logger.warning(
                "posthog_connection_forward_unreachable",
                integration_id=integration.id,
                region=integration.config.get("region"),
                error=str(err),
            )
            return Response(
                {"status": status.HTTP_502_BAD_GATEWAY, "data": {"error": "The target project could not be reached."}},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            body = res.json()
        except ValueError:
            body = None
        # Pass the target's status and body straight through. The target owns the residency policy for
        # what its responses contain, so no scrub happens on this side.
        return Response({"status": res.status_code, "data": body})
