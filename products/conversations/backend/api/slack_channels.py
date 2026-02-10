"""API endpoint for fetching Slack channels using a bot token."""

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

    def post(self, request: Request, *args, **kwargs) -> Response:
        team = request.user.current_team
        bot_token = get_support_slack_bot_token(team)
        if not bot_token:
            return Response(
                {"error": "Support Slack bot token is not configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

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
                channels.extend([{"id": c["id"], "name": c["name"]} for c in result.get("channels", [])])

                cursor = result.get("response_metadata", {}).get("next_cursor")
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
