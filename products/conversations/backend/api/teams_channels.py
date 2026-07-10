from django.db import transaction

import requests
import structlog
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.helpers.impersonation import is_impersonated
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
                {
                    "id": c.get("id"),
                    "name": c.get("displayName"),
                    # "standard" | "shared" | "private" — drives shared-channel
                    # polling and the picker badge. Absent fields are treated as
                    # standard downstream.
                    "membership_type": c.get("membershipType"),
                }
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


class TeamsChannelActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["add", "remove"], required=True)
    team_id = serializers.UUIDField(required=False)
    channel_id = serializers.CharField(required=True, max_length=500)


MAX_TEAMS_CHANNELS = 25


def _seed_teams_channels_from_legacy(settings_blob: dict) -> list[dict]:
    """Seed teams_channels from legacy scalar fields if not yet present."""
    if "teams_channels" in settings_blob and isinstance(settings_blob.get("teams_channels"), list):
        return list(settings_blob["teams_channels"])
    legacy_team_id = settings_blob.get("teams_team_id")
    legacy_channel_id = settings_blob.get("teams_channel_id")
    if legacy_team_id and legacy_channel_id:
        return [
            {
                "team_id": legacy_team_id,
                "team_name": settings_blob.get("teams_team_name"),
                "channel_id": legacy_channel_id,
                "channel_name": settings_blob.get("teams_channel_name"),
            }
        ]
    return []


def _update_legacy_scalars_from_list(settings_blob: dict, channels: list[dict]) -> None:
    """Keep legacy scalar fields in sync with the first entry of teams_channels."""
    if channels:
        first = channels[0]
        settings_blob["teams_team_id"] = first.get("team_id")
        settings_blob["teams_team_name"] = first.get("team_name")
        settings_blob["teams_channel_id"] = first.get("channel_id")
        settings_blob["teams_channel_name"] = first.get("channel_name")
    else:
        settings_blob["teams_team_id"] = None
        settings_blob["teams_team_name"] = None
        settings_blob["teams_channel_id"] = None
        settings_blob["teams_channel_name"] = None


class TeamsSelectChannelView(APIView):
    """Persist the admin's MS Teams group/channel selection for this project.

    Supports two request formats:

    1. **New format (add/remove)**: Incremental updates with ``action`` and ``channel_id``.
       - ``action: "add"``: Requires ``team_id``. Validates the pair against Graph, upserts into ``teams_channels`` (keyed by channel_id).
       - ``action: "remove"``: Removes the entry by ``channel_id``, no Graph call needed.

    2. **Legacy format**: Single ``teams_team_id`` / ``teams_channel_id`` pair.
       - Passing ``teams_team_id: null`` clears the whole selection.
       - Passing a valid ``teams_team_id`` without ``teams_channel_id`` clears just the channel.

    Both formats re-derive display names from Graph (not trusted from client) and keep
    the legacy scalar fields (``teams_team_id``, etc.) in sync from the first list entry.
    """

    permission_classes = [IsAuthenticated, IsConversationsAdmin]
    throttle_classes = [TeamsAdminGraphThrottle]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        # Check if this is a new-format (action-based) request
        if "action" in request.data:
            return self._handle_action_request(request, user)

        # Legacy format
        return self._handle_legacy_request(request, user)

    def _handle_action_request(self, request: Request, user: User) -> Response:
        """Handle new action-based add/remove requests."""
        serializer = TeamsChannelActionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": "invalid_payload", "details": serializer.errors}, status=400)

        action = serializer.validated_data["action"]
        teams_channel_id = serializer.validated_data["channel_id"].strip()

        if not teams_channel_id:
            return Response({"error": "channel_id_required"}, status=400)

        team = user.current_team
        assert team is not None

        if action == "remove":
            return self._handle_remove(team, user, teams_channel_id)

        teams_team_id = serializer.validated_data.get("team_id")
        if not teams_team_id:
            return Response({"error": "team_id_required"}, status=400)

        return self._handle_add(team, user, str(teams_team_id), teams_channel_id)

    def _handle_add(self, team: Team, user: User, teams_team_id: str, teams_channel_id: str) -> Response:
        """Validate and add a team/channel pair."""
        try:
            token = get_graph_token(team)
        except ValueError:
            logger.exception("teams_select_channel_token_error")
            return Response({"error": "Failed to get Teams access token"}, status=400)

        # Validate team access
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
        team_match = next((t for t in joined if str(t.get("id", "")) == teams_team_id), None)
        if not team_match:
            return Response({"error": "team_not_accessible"}, status=400)
        teams_team_name = team_match.get("displayName") or None

        # Validate channel access
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
        channel_match = next((c for c in channels if str(c.get("id", "")) == teams_channel_id), None)
        if not channel_match:
            return Response({"error": "channel_not_accessible"}, status=400)
        teams_channel_name = channel_match.get("displayName") or None

        # Persist: read-modify-write under lock
        with transaction.atomic():
            locked_team = Team.objects.select_for_update().only("conversations_settings").get(pk=team.pk)
            settings_blob = dict(locked_team.conversations_settings or {})

            # Seed from legacy if teams_channels not yet present
            teams_channels = _seed_teams_channels_from_legacy(settings_blob)

            existing_entry = next((c for c in teams_channels if c.get("channel_id") == teams_channel_id), None)

            # Upsert by channel_id (channel_id is unique across teams)
            new_entry = {
                "team_id": teams_team_id,
                "team_name": teams_team_name,
                "channel_id": teams_channel_id,
                "channel_name": teams_channel_name,
                # "standard" | "shared" | "private". Shared/private channels never
                # push ambient messages over the bot webhook, so the per-minute
                # poller pulls them from Graph; standard channels stay webhook-only.
                "membership_type": channel_match.get("membershipType"),
            }
            # Remove existing entry with same channel_id (if any)
            teams_channels = [c for c in teams_channels if c.get("channel_id") != teams_channel_id]
            # Add new entry
            teams_channels.append(new_entry)

            # Cap at max
            if len(teams_channels) > MAX_TEAMS_CHANNELS:
                return Response(
                    {"error": "max_channels_exceeded", "max": MAX_TEAMS_CHANNELS},
                    status=400,
                )

            settings_blob["teams_channels"] = teams_channels
            _update_legacy_scalars_from_list(settings_blob, teams_channels)

            locked_team.conversations_settings = settings_blob
            locked_team.save(update_fields=["conversations_settings"])
            team.conversations_settings = settings_blob

        new_label = f"{teams_team_name} / {teams_channel_name}"
        if existing_entry:
            change = Change(
                type="Team",
                action="changed",
                field="teams_channels",
                before=f"{existing_entry.get('team_name')} / {existing_entry.get('channel_name')}",
                after=new_label,
            )
        else:
            change = Change(
                type="Team",
                action="created",
                field="teams_channels",
                after=new_label,
            )

        log_activity(
            organization_id=team.organization_id,
            team_id=team.pk,
            user=user,
            was_impersonated=is_impersonated(self.request),
            scope="Team",
            item_id=team.pk,
            activity="updated",
            detail=Detail(
                name=str(team.name),
                changes=[change],
            ),
        )

        return Response({"ok": True, "teams_channels": settings_blob.get("teams_channels")})

    def _handle_remove(self, team: Team, user: User, teams_channel_id: str) -> Response:
        """Remove a channel from the configured list."""
        removed_entry: dict | None = None

        with transaction.atomic():
            locked_team = Team.objects.select_for_update().only("conversations_settings").get(pk=team.pk)
            settings_blob = dict(locked_team.conversations_settings or {})

            # Seed from legacy if teams_channels not yet present
            teams_channels = _seed_teams_channels_from_legacy(settings_blob)

            # Find and remove entry
            new_channels = []
            for c in teams_channels:
                if c.get("channel_id") == teams_channel_id:
                    removed_entry = c
                else:
                    new_channels.append(c)

            if removed_entry is None:
                return Response({"error": "channel_not_found"}, status=404)

            settings_blob["teams_channels"] = new_channels
            _update_legacy_scalars_from_list(settings_blob, new_channels)

            locked_team.conversations_settings = settings_blob
            locked_team.save(update_fields=["conversations_settings"])
            team.conversations_settings = settings_blob

        log_activity(
            organization_id=team.organization_id,
            team_id=team.pk,
            user=user,
            was_impersonated=is_impersonated(self.request),
            scope="Team",
            item_id=team.pk,
            activity="updated",
            detail=Detail(
                name=str(team.name),
                changes=[
                    Change(
                        type="Team",
                        action="deleted",
                        field="teams_channels",
                        before=f"{removed_entry.get('team_name')} / {removed_entry.get('channel_name')}",
                    ),
                ],
            ),
        )

        return Response({"ok": True, "teams_channels": settings_blob.get("teams_channels")})

    def _handle_legacy_request(self, request: Request, user: User) -> Response:
        """Handle legacy single team/channel pair request for backwards compatibility."""
        serializer = TeamsSelectChannelRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": "invalid_payload", "details": serializer.errors}, status=400)

        teams_team_id_val = serializer.validated_data.get("teams_team_id")
        teams_team_id = str(teams_team_id_val) if teams_team_id_val else None
        teams_channel_id = (serializer.validated_data.get("teams_channel_id") or "").strip() or None

        if teams_channel_id and not teams_team_id:
            return Response({"error": "channel_id_requires_team_id"}, status=400)

        team = user.current_team
        assert team is not None

        try:
            token = get_graph_token(team)
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

        with transaction.atomic():
            locked_team = Team.objects.select_for_update().only("conversations_settings").get(pk=team.pk)
            settings_blob = dict(locked_team.conversations_settings or {})

            # For legacy requests, we replace the single-entry list (backwards-compatible behavior)
            if teams_team_id and teams_channel_id:
                settings_blob["teams_channels"] = [
                    {
                        "team_id": teams_team_id,
                        "team_name": teams_team_name,
                        "channel_id": teams_channel_id,
                        "channel_name": teams_channel_name,
                    }
                ]
            else:
                # Clearing — remove the list too
                settings_blob.pop("teams_channels", None)

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
            was_impersonated=is_impersonated(request),
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
