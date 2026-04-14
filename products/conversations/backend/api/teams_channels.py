import requests
import structlog
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.user import User

from products.conversations.backend.permissions import IsConversationsAdmin
from products.conversations.backend.support_teams import get_graph_token

logger = structlog.get_logger(__name__)

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


class TeamsChannelRequestSerializer(serializers.Serializer):
    team_id = serializers.UUIDField(required=True)


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
