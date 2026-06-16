"""API endpoint for fetching Slack channels using a bot token."""

from typing import Any, cast

import structlog
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from products.conversations.backend.support_slack import get_support_slack_bot_token

logger = structlog.get_logger(__name__)
MAX_CHANNEL_PAGES = 100


class SlackChannelsView(APIView):
    """Fetch Slack channels using the support bot token from env settings."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        team = request.user.current_team  # type: ignore[union-attr]
        bot_token = get_support_slack_bot_token(team)  # type: ignore[arg-type]
        if not bot_token:
            return Response(
                {"error": "Support Slack bot token is not configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Broadcasts can only post to channels the bot belongs to (chat.postMessage
        # returns not_in_channel otherwise), so the broadcast picker passes members_only.
        members_only = bool(request.data.get("members_only"))

        try:
            client = WebClient(token=bot_token)
            channels = []
            cursor = None

            # Paginate through all channels
            for _ in range(MAX_CHANNEL_PAGES):
                result = client.conversations_list(
                    types="public_channel,private_channel",
                    exclude_archived=True,
                    limit=1000,
                    cursor=cursor,
                )
                for c in cast(list[dict[str, Any]], result.get("channels") or []):
                    # conversations_list reports is_member for public channels; private
                    # channels are only returned when the bot is already in them, so treat
                    # a returned private channel as a member channel when the flag is absent.
                    is_member = bool(c.get("is_member", c.get("is_private", False)))
                    if members_only and not is_member:
                        continue
                    channels.append({"id": c["id"], "name": c["name"], "is_member": is_member})

                response_metadata = result.get("response_metadata") or {}
                cursor = response_metadata.get("next_cursor", "")
                if not cursor:
                    break
            else:
                logger.warning("slack_channels_fetch_too_many_pages", max_pages=MAX_CHANNEL_PAGES)
                return Response(
                    {"error": "Too many channel pages returned by Slack"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Sort by name for easier selection
            channels.sort(key=lambda c: c["name"].lower())
            return Response({"channels": channels})
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
