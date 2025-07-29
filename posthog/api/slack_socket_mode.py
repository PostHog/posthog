import structlog
from typing import Optional
from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from posthog.models.instance_setting import get_instance_settings

logger = structlog.get_logger(__name__)


class SlackSocketModeClient:
    """
    Slack Socket Mode client for handling real-time events and slash commands.
    """

    def __init__(self, app_token: str, bot_token: str):
        """
        Initialize the Socket Mode client.

        Args:
            app_token: Slack app-level token (starts with xapp-)
            bot_token: Bot user OAuth token (starts with xoxb-)
        """
        self.web_client = WebClient(token=bot_token)
        self.socket_mode_client = SocketModeClient(app_token=app_token, web_client=self.web_client)

        # Register event handlers
        self.socket_mode_client.socket_mode_request_listeners.append(self._handle_socket_mode_request)

    def _handle_socket_mode_request(self, client, req):
        """
        Handle incoming socket mode requests (internal wrapper for proper typing).
        """
        if req.type == "events_api" and req.payload.get("event", {}).get("type") == "app_mention":
            self.handle_app_mention(client, req)
        else:
            pass

    def handle_app_mention(self, client: SocketModeClient, req: SocketModeRequest):
        """
        Handle Events API events.
        """
        event_data = req.payload
        event = event_data.get("event", {})

        logger.info(f"Received event: {event}")

        self.web_client.chat_postMessage(
            channel=event.get("channel"), text="Hello world!", username="PostHog Max", icon_emoji=":hedgehog:"
        )

        # Acknowledge the request
        response = SocketModeResponse(envelope_id=req.envelope_id)
        client.send_socket_mode_response(response)

    def start(self):
        """
        Start the Socket Mode client.
        """
        logger.info("Starting Slack Socket Mode client...")
        self.socket_mode_client.connect()
        logger.info("Slack Socket Mode client connected")

    def disconnect(self):
        """
        Disconnect the Socket Mode client.
        """
        logger.info("Disconnecting Slack Socket Mode client...")
        self.socket_mode_client.disconnect()
        logger.info("Slack Socket Mode client disconnected")

    @classmethod
    def from_settings(cls) -> Optional["SlackSocketModeClient"]:
        """
        Create a SlackSocketModeClient from instance settings.

        Returns:
            SlackSocketModeClient instance or None if not configured
        """
        settings = get_instance_settings(
            [
                "SLACK_APP_TOKEN",  # Socket mode app token
                "SLACK_BOT_TOKEN",  # Bot token from OAuth integration
            ]
        )

        app_token = settings.get("SLACK_APP_TOKEN")
        bot_token = settings.get("SLACK_BOT_TOKEN")

        if not app_token or not bot_token:
            logger.warning("Slack Socket Mode not configured - missing SLACK_APP_TOKEN or SLACK_BOT_TOKEN")
            return None

        return cls(app_token=app_token, bot_token=bot_token)
