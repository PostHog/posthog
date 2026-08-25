"""API endpoint for fetching Slack channels using the SupportHog bot token."""

from typing import Any

import structlog
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from slack_sdk.errors import SlackApiError

from products.conversations.backend.support_slack_channels import (
    SupportSlackChannelsUnavailable,
    SupportSlackNotConfigured,
    list_support_bot_channels,
)

logger = structlog.get_logger(__name__)


class SlackChannelsView(APIView):
    """Fetch Slack channels using the support bot token from env settings."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        team = request.user.current_team  # type: ignore[union-attr]
        # members_only restricts to channels the bot belongs to (chat.postMessage returns
        # not_in_channel otherwise); callers that only route replies can omit it.
        members_only = bool(request.data.get("members_only"))

        try:
            resolved = list_support_bot_channels(team, members_only=members_only)  # type: ignore[arg-type]
        except SupportSlackNotConfigured:
            return Response(
                {"error": "Support Slack bot token is not configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except SupportSlackChannelsUnavailable:
            return Response(
                {"error": "Too many channel pages returned by Slack"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except SlackApiError as e:
            logger.warning("slack_channels_fetch_failed", error=str(e))
            return Response(
                {"error": f"Slack API error: {e.response.get('error', 'unknown')}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.exception("slack_channels_fetch_error", error=str(e))
            return Response(
                {"error": "Failed to fetch channels"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Keep this endpoint's response shape ({id, name}); is_member is an internal detail the
        # announcements picker consumes via its own action, not part of this contract.
        return Response({"channels": [{"id": c["id"], "name": c["name"]} for c in resolved]})
