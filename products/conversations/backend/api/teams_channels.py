from django.db import transaction

import requests
import structlog
from loginas.utils import is_impersonated_session
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.instance_setting import get_instance_settings
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rate_limit import TeamsAdminGraphThrottle

from products.conversations.backend.permissions import IsConversationsAdmin
from products.conversations.backend.support_teams import get_graph_token

logger = structlog.get_logger(__name__)

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


class TeamsChannelRequestSerializer(serializers.Serializer):
    team_id = serializers.UUIDField(required=True)


class TeamsInstallAppRequestSerializer(serializers.Serializer):
    team_id = serializers.UUIDField(required=True)


class TeamsTeamsView(APIView):
    """List MS Teams groups the authenticated user has joined."""

    permission_classes = [IsAuthenticated, IsConversationsAdmin]
    throttle_classes = [TeamsAdminGraphThrottle]

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
    throttle_classes = [TeamsAdminGraphThrottle]

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

    Requires the manifest to already exist in the tenant's app catalog — via
    the public Teams Store (keyed by ``SUPPORT_TEAMS_CATALOG_APP_ID``) or,
    fallback, uploaded to the tenant's org catalog by an admin. For the
    org-catalog fallback the tenant-scoped app id must match the instance
    setting (we deliberately don't accept a caller-supplied override so a
    compromised PostHog admin can't point this at an arbitrary tenant-catalog
    app and install it with the bot's
    ``TeamsAppInstallation.ReadWriteForTeam`` grant).

    Idempotent: if the app is already installed (Graph returns 409 Conflict),
    we return ok=True so the frontend can proceed to the channel-selection step.
    """

    permission_classes = [IsAuthenticated, IsConversationsAdmin]
    throttle_classes = [TeamsAdminGraphThrottle]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        serializer = TeamsInstallAppRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": "team_id must be a valid UUID"}, status=400)
        teams_team_id = str(serializer.validated_data["team_id"])

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


class TeamsSelectChannelRequestSerializer(serializers.Serializer):
    teams_team_id = serializers.UUIDField(required=False, allow_null=True)
    teams_channel_id = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=500)


class TeamsSelectChannelView(APIView):
    """Persist the admin's MS Teams group/channel selection for this project.

    Replaces writing ``teams_team_id`` / ``teams_channel_id`` (and their display
    names) through the generic ``PATCH /api/projects/:id`` path. Those fields
    are on ``managed_key``, so the only way to set them is via this endpoint,
    which re-validates the IDs against Graph under the current OAuth grant. The
    display names are always re-derived from Graph and never trusted from the
    client to avoid spoofed audit-log values like "channel X was configured".

    Passing ``teams_team_id: null`` (or omitting it) clears the whole selection.
    Passing a valid ``teams_team_id`` without ``teams_channel_id`` clears just
    the channel.
    """

    permission_classes = [IsAuthenticated, IsConversationsAdmin]
    throttle_classes = [TeamsAdminGraphThrottle]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        serializer = TeamsSelectChannelRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": "invalid_payload", "details": serializer.errors}, status=400)

        teams_team_id_val = serializer.validated_data.get("teams_team_id")
        teams_team_id = str(teams_team_id_val) if teams_team_id_val else None
        teams_channel_id = (serializer.validated_data.get("teams_channel_id") or "").strip() or None

        if teams_channel_id and not teams_team_id:
            return Response({"error": "channel_id_requires_team_id"}, status=400)

        try:
            token = get_graph_token(user.current_team)
        except ValueError:
            logger.exception("teams_select_channel_token_error")
            return Response({"error": "Failed to get Teams access token"}, status=400)

        teams_team_name: str | None = None
        teams_channel_name: str | None = None

        if teams_team_id:
            try:
                resp = requests.get(
                    f"{GRAPH_API_BASE}/me/joinedTeams",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=15,
                )
            except Exception:
                logger.exception("teams_select_channel_joined_teams_error")
                return Response({"error": "graph_network_error"}, status=502)
            if resp.status_code != 200:
                logger.warning("teams_select_channel_joined_teams_failed", status=resp.status_code)
                return Response({"error": "graph_error"}, status=502)

            joined = resp.json().get("value", []) or []
            match = next((t for t in joined if str(t.get("id", "")) == teams_team_id), None)
            if not match:
                return Response({"error": "team_not_accessible"}, status=400)
            teams_team_name = match.get("displayName") or None

        if teams_channel_id and teams_team_id:
            try:
                resp = requests.get(
                    f"{GRAPH_API_BASE}/teams/{teams_team_id}/channels",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=15,
                )
            except Exception:
                logger.exception("teams_select_channel_channels_error")
                return Response({"error": "graph_network_error"}, status=502)
            if resp.status_code != 200:
                logger.warning("teams_select_channel_channels_failed", status=resp.status_code)
                return Response({"error": "graph_error"}, status=502)

            channels = resp.json().get("value", []) or []
            match = next((c for c in channels if str(c.get("id", "")) == teams_channel_id), None)
            if not match:
                return Response({"error": "channel_not_accessible"}, status=400)
            teams_channel_name = match.get("displayName") or None

        team = user.current_team
        with transaction.atomic():
            # Re-read under row lock, as in save_teams_token, so we don't
            # clobber a concurrent conversations_settings write.
            locked_team = Team.objects.select_for_update().only("conversations_settings").get(pk=team.pk)
            settings_blob = dict(locked_team.conversations_settings or {})
            settings_blob["teams_team_id"] = teams_team_id
            settings_blob["teams_team_name"] = teams_team_name
            settings_blob["teams_channel_id"] = teams_channel_id
            settings_blob["teams_channel_name"] = teams_channel_name
            locked_team.conversations_settings = settings_blob
            locked_team.save(update_fields=["conversations_settings"])
            team.conversations_settings = settings_blob

        log_activity(
            organization_id=team.organization_id,
            team_id=team.pk,
            user=user,
            was_impersonated=is_impersonated_session(request),
            scope="Team",
            item_id=team.pk,
            activity="updated",
            detail=Detail(
                name=str(team.name),
                changes=[
                    Change(
                        type="Team",
                        action="changed",
                        field="teams_channel_id",
                        after=teams_channel_id,
                    ),
                ],
            ),
        )

        return Response(
            {
                "teams_team_id": teams_team_id,
                "teams_team_name": teams_team_name,
                "teams_channel_id": teams_channel_id,
                "teams_channel_name": teams_channel_name,
            }
        )
