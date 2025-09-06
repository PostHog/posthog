from urllib.parse import quote
import structlog
from uuid import uuid4
import asyncio
from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from posthog.models.instance_setting import get_instance_setting
from posthog.models.user import User
from posthog.models.team.team import Team
from posthog.schema import (
    AssistantMessage,
    HumanMessage,
    AssistantEventType,
    AssistantTrendsQuery,
    AssistantFunnelsQuery,
    AssistantRetentionQuery,
    AssistantHogQLQuery,
    InsightVizNode,
    VisualizationMessage,
)
from ee.models.assistant import Conversation
from ee.hogai.stream.conversation_stream import ConversationStreamManager
from ee.hogai.utils.types import AssistantMode
from posthog.temporal.ai.conversation import AssistantConversationRunnerWorkflowInputs
from posthog.utils import absolute_uri

logger = structlog.get_logger(__name__)


class SlackSocketModeClient:
    """
    Slack Socket Mode client for handling real-time events and slash commands.
    """

    def __init__(self):
        self.web_client = WebClient(token=get_instance_setting("SLACK_BOT_TOKEN"))
        self.socket_mode_client = SocketModeClient(
            app_token=get_instance_setting("SLACK_APP_TOKEN"), web_client=self.web_client, concurrency=100
        )

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
        Handle Events API events by invoking Max AI.
        """
        event_data = req.payload
        event = event_data.get("event", {})

        logger.info(f"Received event: {event}")

        channel = event.get("channel")
        text = event.get("text", "")
        mention_ts = event.get("ts")
        thread_ts = event.get("thread_ts") or mention_ts

        # Acknowledge the request immediately
        response = SocketModeResponse(envelope_id=req.envelope_id)
        client.send_socket_mode_response(response)

        self.web_client.reactions_add(channel=channel, timestamp=mention_ts, name="eyes")

        # Process with Max AI asynchronously
        asyncio.run(self._handle_max_ai_async(channel, text, thread_ts))

        self.web_client.reactions_remove(channel=channel, timestamp=mention_ts, name="eyes")
        self.web_client.reactions_add(channel=channel, timestamp=mention_ts, name="white_check_mark")

    async def _handle_max_ai_async(self, channel: str, text: str, thread_ts: str):
        user = await User.objects.alast()  # TODO
        team = await Team.objects.alast()  # TODO
        try:
            # Create conversation
            conversation_id = uuid4()
            conversation = await Conversation.objects.acreate(user=user, team=team, id=conversation_id)

            # Create workflow inputs
            message = HumanMessage(content=text)
            workflow_inputs = AssistantConversationRunnerWorkflowInputs(
                team_id=team.id,
                user_id=user.pk,
                conversation_id=conversation.id,
                message=message.model_dump(),
                contextual_tools=None,
                is_new_conversation=True,
                trace_id=uuid4(),
                session_id=None,
                mode=AssistantMode.ASSISTANT,
                billing_context=None,
            )

            # Stream AI responses
            stream_manager = ConversationStreamManager(conversation)
            generated_query: (
                AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery | AssistantHogQLQuery | None
            ) = None
            async for event_type, payload in stream_manager.astream(workflow_inputs):
                # Only handle message events, filter out value and debug updates
                if event_type == AssistantEventType.MESSAGE:
                    if isinstance(payload, VisualizationMessage):
                        generated_query = payload.answer
                    if isinstance(payload, AssistantMessage) and payload.id:  # ID means the message has been finalized
                        content = str(payload.content)
                        if getattr(payload, "tool_calls", None):
                            content += " 🔄"
                        if generated_query is not None:
                            if isinstance(generated_query, AssistantHogQLQuery):
                                new_insight_url = absolute_uri(
                                    f"/project/{team.id}/sql?open_query={quote(generated_query.query)}"
                                )
                            else:
                                insight_viz_json = InsightVizNode.model_construct(
                                    source=generated_query
                                ).model_dump_json(exclude_none=True)
                                new_insight_url = absolute_uri(
                                    # For some god-forsaken frontend reason it's important
                                    # that there's a space (%20) in the URL-encoded value of `q`.
                                    # Otherwise the query is not parsed correctly by insightSceneLogic!
                                    f"/project/{team.id}/insights/new#q={quote(insight_viz_json)}%20"
                                )
                            content += f" <{new_insight_url}|Query right here.>"
                        generated_query = None  # Reset back again
                        self.web_client.chat_postMessage(
                            channel=channel,
                            thread_ts=thread_ts,
                            text=content,
                            username="PostHog Max",
                            icon_emoji=":hedgehog:",
                        )

        except Exception as e:
            logger.exception("Error handling Max AI request", error=e)
            # Post error message to Slack
            self.web_client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Sorry, I encountered an error processing your request.",
                username="PostHog Max",
                icon_emoji=":hedgehog:",
            )

    def connect(self):
        """
        Start the Socket Mode client.
        """
        logger.info("Starting Slack Socket Mode client...")
        self.socket_mode_client.connect()
        logger.info("Slack Socket Mode client connected")

    def close(self):
        """
        Disconnect the Socket Mode client.
        """
        logger.info("Disconnecting Slack Socket Mode client...")
        self.socket_mode_client.close()
        logger.info("Slack Socket Mode client disconnected")
