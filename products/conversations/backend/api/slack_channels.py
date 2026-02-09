"""API endpoint for fetching Slack channels using a bot token."""

import structlog
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = structlog.get_logger(__name__)


class SlackChannelsView(APIView):
    """Fetch Slack channels using a bot token."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, *args, **kwargs) -> Response:
        bot_token = request.data.get("bot_token")
        if not bot_token:
            return Response(
                {"error": "bot_token is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            client = WebClient(token=bot_token)
            channels = []
            cursor = None

            # Paginate through all channels
            while True:
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
