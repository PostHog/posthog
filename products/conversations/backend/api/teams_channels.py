import requests
import structlog
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.instance_setting import get_instance_settings
from posthog.models.user import User

from products.conversations.backend.permissions import IsConversationsAdmin
from products.conversations.backend.support_teams import get_graph_token

logger = structlog.get_logger(__name__)

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


class TeamsChannelRequestSerializer(serializers.Serializer):
    team_id = serializers.UUIDField(required=True)


class TeamsInstallAppRequestSerializer(serializers.Serializer):
    team_id = serializers.UUIDField(required=True)
    app_id = serializers.UUIDField(required=False, allow_null=True)


class TeamsTeamsView(APIView):
    """List MS Teams groups the authenticated user has joined."""

    permission_classes = [IsAuthenticated, IsConversationsAdmin]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        try:
            token = get_graph_token(user.current_team)
        except ValueError:
            logger.exception("teams_list_teams_token_error")
            return Response({"error": "Failed to get Teams access token"}, status=400)

        try:
            resp = requests.get(
                f"{GRAPH_API_BASE}/me/joinedTeams",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning("teams_list_teams_failed", status=resp.status_code)
                return Response({"error": "Failed to list Teams"}, status=502)

            data = resp.json()
            teams_list = [
                {"id": t.get("id"), "name": t.get("displayName")}
                for t in data.get("value", [])
                if t.get("id") and t.get("displayName")
            ]
            return Response({"teams": teams_list})
        except Exception:
            logger.exception("teams_list_teams_error")
            return Response({"error": "Failed to list Teams"}, status=502)


class TeamsChannelsView(APIView):
    """List channels in a specific MS Teams team."""

    permission_classes = [IsAuthenticated, IsConversationsAdmin]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        serializer = TeamsChannelRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": "team_id must be a valid UUID"}, status=400)
        teams_team_id = str(serializer.validated_data["team_id"])

        try:
            token = get_graph_token(user.current_team)
        except ValueError:
            logger.exception("teams_list_channels_token_error")
            return Response({"error": "Failed to get Teams access token"}, status=400)

        try:
            resp = requests.get(
                f"{GRAPH_API_BASE}/teams/{teams_team_id}/channels",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning("teams_list_channels_failed", status=resp.status_code, teams_team_id=teams_team_id)
                return Response({"error": "Failed to list channels"}, status=502)

            data = resp.json()
            channels = [
                {"id": c.get("id"), "name": c.get("displayName")}
                for c in data.get("value", [])
                if c.get("id") and c.get("displayName")
            ]
            return Response({"channels": channels})
        except Exception:
            logger.exception("teams_list_channels_error")
            return Response({"error": "Failed to list channels"}, status=502)


class TeamsInstallAppView(APIView):
    """Install the SupportHog Teams app into a selected MS Teams group.

    Requires the manifest to already exist in the tenant's app catalog — via the
    public Teams Store (default, keyed by SUPPORT_TEAMS_CATALOG_APP_ID) or,
    fallback, uploaded to the tenant's org catalog by an admin. In the latter
    case the client can supply an override ``app_id`` in the request body.

    Idempotent: if the app is already installed (Graph returns 409 Conflict),
    we return ok=True so the frontend can proceed to the channel-selection step.
    """

    permission_classes = [IsAuthenticated, IsConversationsAdmin]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        serializer = TeamsInstallAppRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": "team_id must be a valid UUID"}, status=400)
        teams_team_id = str(serializer.validated_data["team_id"])
        override_catalog_app_id = serializer.validated_data.get("app_id")

        if override_catalog_app_id:
            catalog_app_id = str(override_catalog_app_id)
        else:
            settings_payload = get_instance_settings(["SUPPORT_TEAMS_CATALOG_APP_ID"])
            catalog_app_id = str(settings_payload.get("SUPPORT_TEAMS_CATALOG_APP_ID") or "").strip()
        if not catalog_app_id:
            return Response({"error": "catalog_not_configured"}, status=503)

        try:
            token = get_graph_token(user.current_team)
        except ValueError:
            logger.exception("teams_install_app_token_error")
            return Response({"error": "Failed to get Teams access token"}, status=400)

        try:
            resp = requests.post(
                f"{GRAPH_API_BASE}/teams/{teams_team_id}/installedApps",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    # Graph accepts both the public (appcatalogs) and tenant-scoped
                    # (/teamwork/...) bindings for apps published via either path.
                    "teamsApp@odata.bind": (f"https://graph.microsoft.com/v1.0/appCatalogs/teamsApps/{catalog_app_id}"),
                },
                timeout=15,
            )
        except Exception:
            logger.exception("teams_install_app_network_error", teams_team_id=teams_team_id)
            return Response({"error": "install_network_error"}, status=502)

        if resp.status_code in (200, 201, 204):
            return Response({"ok": True, "status": "installed"})

        if resp.status_code == 409:
            return Response({"ok": True, "status": "already_installed"})

        # Graph returns 404 with "error.code=NotFound" when the catalog app id
        # isn't visible to this tenant. That happens when the tenant's app setup
        # policy blocks the public Teams Store listing, so the admin needs to
        # upload the zip to their org catalog. Surface a distinct code so the
        # frontend can render actionable guidance + Retry.
        body = ""
        try:
            body = resp.text[:500]
        except Exception:
            pass

        if resp.status_code == 404:
            logger.warning(
                "teams_install_app_not_in_catalog",
                teams_team_id=teams_team_id,
                catalog_app_id=catalog_app_id,
                body=body,
            )
            return Response({"error": "app_not_found_in_catalog"}, status=404)

        if resp.status_code == 403:
            logger.warning(
                "teams_install_app_forbidden",
                teams_team_id=teams_team_id,
                catalog_app_id=catalog_app_id,
                body=body,
            )
            return Response({"error": "forbidden"}, status=403)

        logger.warning(
            "teams_install_app_failed",
            status=resp.status_code,
            teams_team_id=teams_team_id,
            catalog_app_id=catalog_app_id,
            body=body,
        )
        return Response({"error": "install_failed"}, status=502)
