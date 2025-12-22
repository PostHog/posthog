import re
import json
import random
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.conf import settings

import structlog
from markdown_to_mrkdwn import SlackMarkdownConverter
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.ai.base import AgentBaseWorkflow

from products.slack_app.backend.slack_thread import SlackThreadContext

if TYPE_CHECKING:
    from posthog.models.integration import Integration

logger = structlog.get_logger(__name__)
mrkdown_converter = SlackMarkdownConverter()

THINKING_MESSAGES = [
    "Booping",
    "Crunching",
    "Digging",
    "Fetching",
    "Inferring",
    "Indexing",
    "Juggling",
    "Noodling",
    "Peeking",
    "Percolating",
    "Poking",
    "Pondering",
    "Scanning",
    "Scrambling",
    "Sifting",
    "Sniffing",
    "Spelunking",
    "Tinkering",
    "Unraveling",
    "Decoding",
    "Trekking",
    "Sorting",
    "Trimming",
    "Mulling",
    "Surfacing",
    "Rummaging",
    "Scouting",
    "Scouring",
    "Threading",
    "Hunting",
    "Swizzling",
    "Grokking",
    "Hedging",
    "Scheming",
    "Unfurling",
    "Puzzling",
    "Dissecting",
    "Stacking",
    "Snuffling",
    "Hashing",
    "Clustering",
    "Teasing",
    "Cranking",
    "Merging",
    "Snooping",
    "Rewiring",
    "Bundling",
    "Linking",
    "Mapping",
    "Tickling",
    "Flicking",
    "Hopping",
    "Rolling",
    "Zipping",
    "Twisting",
    "Blooming",
    "Sparking",
    "Nesting",
    "Looping",
    "Wiring",
    "Snipping",
    "Zoning",
    "Tracing",
    "Warping",
    "Twinkling",
    "Flipping",
    "Priming",
    "Snagging",
    "Scuttling",
    "Framing",
    "Sharpening",
    "Flibbertigibbeting",
    "Kerfuffling",
    "Dithering",
    "Discombobulating",
    "Rambling",
    "Befuddling",
    "Waffling",
    "Muckling",
    "Hobnobbing",
    "Galumphing",
    "Puttering",
    "Whiffling",
    "Thinking",
]

SLACK_CONVERSATION_WORKFLOW_TIMEOUT = 60 * 60  # 60 minutes - coding tasks can take a while
SLACK_CONVERSATION_ACTIVITY_RETRY_INTERVAL = 1  # 1 second
SLACK_CONVERSATION_ACTIVITY_RETRY_MAX_INTERVAL = 30 * 60  # 30 minutes
SLACK_CONVERSATION_ACTIVITY_RETRY_MAX_ATTEMPTS = 3
SLACK_CONVERSATION_ACTIVITY_HEARTBEAT_TIMEOUT = 5 * 60  # 5 minutes


@dataclass
class SlackConversationRunnerWorkflowInputs:
    """Inputs for the Slack conversation workflow."""

    team_id: int
    integration_id: int
    channel: str
    thread_ts: str
    initial_message_ts: str
    user_message_ts: str | None
    messages: list[dict[str, Any]]
    slack_thread_key: str
    user_id: int
    conversation_id: str | None = None  # Provided if continuing an existing conversation


@workflow.defn(name="slack-conversation-processing")
class SlackConversationRunnerWorkflow(AgentBaseWorkflow):
    """Temporal workflow for processing Slack conversations with AI."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SlackConversationRunnerWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SlackConversationRunnerWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: SlackConversationRunnerWorkflowInputs) -> None:
        """Execute the Slack conversation workflow."""
        await workflow.execute_activity(
            process_slack_conversation_activity,
            inputs,
            start_to_close_timeout=timedelta(seconds=SLACK_CONVERSATION_WORKFLOW_TIMEOUT),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=SLACK_CONVERSATION_ACTIVITY_RETRY_INTERVAL),
                maximum_interval=timedelta(seconds=SLACK_CONVERSATION_ACTIVITY_RETRY_MAX_INTERVAL),
                maximum_attempts=SLACK_CONVERSATION_ACTIVITY_RETRY_MAX_ATTEMPTS,
            ),
            heartbeat_timeout=timedelta(seconds=SLACK_CONVERSATION_ACTIVITY_HEARTBEAT_TIMEOUT),
        )


@activity.defn
async def process_slack_conversation_activity(inputs: SlackConversationRunnerWorkflowInputs) -> None:
    """Process a Slack conversation with the AI agent.

    Args:
        inputs: Workflow inputs containing Slack thread info and messages
    """
    from urllib.parse import quote

    from django.conf import settings

    from posthog.schema import (
        ArtifactMessage,
        AssistantHogQLQuery,
        AssistantMessage,
        HumanMessage,
        VisualizationArtifactContent,
    )

    from posthog.models import Team, User
    from posthog.models.integration import Integration

    from ee.hogai.chat_agent.runner import ChatAgentRunner
    from ee.models import Conversation

    team = await Team.objects.aget(id=inputs.team_id)
    integration = await Integration.objects.aget(id=inputs.integration_id)
    user = await User.objects.aget(id=inputs.user_id)

    # Get or create conversation for this Slack thread, keyed by slack_thread_key
    # First, fetch workspace domain from Slack API if we don't have it yet
    slack_workspace_domain = await _get_slack_workspace_domain(integration)

    if inputs.conversation_id:
        # Continuing an existing conversation
        conversation, created = await Conversation.objects.aget_or_create(
            id=inputs.conversation_id,
            defaults={
                "team": team,
                "user": user,
                "type": "slack",
                "slack_thread_key": inputs.slack_thread_key,
                "slack_workspace_domain": slack_workspace_domain,
            },
        )
    else:
        # New conversation - use slack_thread_key as the unique identifier
        conversation, created = await Conversation.objects.aget_or_create(
            team=team,
            slack_thread_key=inputs.slack_thread_key,
            defaults={"user": user, "type": "slack", "slack_workspace_domain": slack_workspace_domain},
        )

    # Update domain if it was missing (for existing conversations)
    if not created and not conversation.slack_workspace_domain and slack_workspace_domain:
        conversation.slack_workspace_domain = slack_workspace_domain
        await conversation.asave(update_fields=["slack_workspace_domain"])

    is_new_conversation = created

    # Join all Slack messages into a single HumanMessage
    message_texts = (
        ["_This conversation is in a Slack thread, using Slack's native Markdown._"] if is_new_conversation else []
    )
    for msg in inputs.messages:
        username = msg.get("user", "Unknown")
        text = msg.get("text", "")
        message_texts.append(f"{username}: {text}")

    combined_message = "\n\n".join(message_texts)
    human_message = HumanMessage(content=combined_message)

    # Create Slack thread context for task workflows to post updates
    slack_thread_context = SlackThreadContext(
        integration_id=inputs.integration_id,
        channel=inputs.channel,
        thread_ts=inputs.thread_ts,
    )

    assistant = ChatAgentRunner(
        team,
        conversation,
        new_message=human_message,
        user=user,
        is_new_conversation=is_new_conversation,
        slack_thread_context=slack_thread_context,
    )

    # Build conversation URL for the "View chat in PostHog" button
    conversation_url = f"{settings.SITE_URL}/project/{team.id}/ai?chat={conversation.id}"

    # Start background task to update the "working on it" message with thinking messages
    async def update_thinking_message():
        start_time = datetime.now()
        while True:
            await asyncio.sleep(3)
            thinking_message = f"I'm {random.choice(THINKING_MESSAGES).lower()}..."
            # After a longer period, add a note to the thinking message, so that the user doesn't feel like we're stuck
            elapsed_seconds = (datetime.now() - start_time).total_seconds()
            if elapsed_seconds >= 120:
                thinking_message += " (This is taking a little longer, hang tight.)"
            await _update_slack_message(
                integration, inputs.channel, inputs.initial_message_ts, thinking_message, conversation_url
            )

    thinking_task = asyncio.create_task(update_thinking_message())

    # Collect all messages from the stream
    assistant_messages: list[AssistantMessage] = []
    artifact_messages: list[ArtifactMessage] = []

    try:
        async for _event_type, message in assistant.astream():
            if isinstance(message, AssistantMessage):
                assistant_messages.append(message)
            elif isinstance(message, ArtifactMessage):
                artifact_messages.append(message)
            activity.heartbeat()
    finally:
        thinking_task.cancel()
        try:
            await thinking_task
        except asyncio.CancelledError:
            pass

    # Get the final response from the last AssistantMessage
    final_response = assistant_messages[-1].content if assistant_messages else None

    # Build query URLs from ArtifactMessages with VisualizationArtifactContent
    generated_queries: list[tuple[str, str]] = []  # (title, url)
    viz_artifacts: list[VisualizationArtifactContent] = [
        msg.content for msg in artifact_messages if isinstance(msg.content, VisualizationArtifactContent)
    ]
    for viz_idx, viz in enumerate(viz_artifacts):
        title = f"Query {viz_idx + 1}"  # TODO: Use actual query title
        if isinstance(viz.query, AssistantHogQLQuery):
            query_url = f"{settings.SITE_URL}/project/{team.id}/sql?open_query={quote(viz.query.query)}"
        else:
            wrapped_query = {"kind": "InsightVizNode", "source": viz.query.model_dump(exclude_none=True)}
            query_url = f"{settings.SITE_URL}/project/{team.id}/insights/new#q={quote(json.dumps(wrapped_query))}"
        generated_queries.append((title, query_url))

    # Append queries section if any were generated
    if final_response and generated_queries:
        queries_section = "\n\nSources:\n" + "\n".join(f"- <{url}|{title}>" for title, url in generated_queries)
        final_response += queries_section

    # Replace loading reaction with checkmark on user's message
    if inputs.user_message_ts:
        await _remove_slack_reaction(integration, inputs.channel, inputs.user_message_ts, "hourglass_flowing_sand")
        await _add_slack_reaction(integration, inputs.channel, inputs.user_message_ts, "white_check_mark")

    # Build conversation URL for the "View chat in PostHog" button
    conversation_url = f"{settings.SITE_URL}/project/{team.id}/ai?chat={conversation.id}"

    # Post the final response as a new message, then delete the initial "working on it" message
    # (new messages trigger notifications, updates don't)
    # We post first so that if posting fails, the user still sees the "working on it" message
    if final_response:
        await _post_slack_message(
            integration,
            inputs.channel,
            inputs.thread_ts,
            final_response,
            conversation_url=conversation_url,
        )
        logger.info(
            "slack_conversation_response_sent",
            team_id=inputs.team_id,
            channel=inputs.channel,
            thread_ts=inputs.thread_ts,
        )
    else:
        await _post_slack_message(
            integration,
            inputs.channel,
            inputs.thread_ts,
            "Sorry, I couldn't generate a response. Please try again.",
            conversation_url=conversation_url,
        )

    await _delete_slack_message(integration, inputs.channel, inputs.initial_message_ts)


def _absolutize_markdown_links(text: str) -> str:
    """Prepend SITE_URL to absolute-path Markdown links (e.g. [text](/path) -> [text](https://example.com/path))."""

    def replace_link(match: re.Match) -> str:
        link_text = match.group(1)
        path = match.group(2)
        return f"[{link_text}]({settings.SITE_URL}{path})"

    # Match [text](/path) where path starts with / but not // (which would be protocol-relative)
    return re.sub(r"\[([^\]]+)\]\((/(?!/)[^)]*)\)", replace_link, text)


def _build_slack_message_blocks(text: str, conversation_url: str | None = None) -> list[dict]:
    """Build Slack message blocks from text."""
    blocks: list[dict] = []

    text = _absolutize_markdown_links(text)
    mrkdwn_text = mrkdown_converter.convert(text)
    paragraphs = mrkdwn_text.split("\n\n")
    for para in paragraphs:
        if para.strip():
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": para}})

    if conversation_url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View chat in PostHog", "emoji": True},
                        "url": conversation_url,
                    }
                ],
            }
        )

    return blocks


async def _post_slack_message(
    integration: "Integration",
    channel: str,
    thread_ts: str,
    text: str,
    conversation_url: str | None = None,
) -> None:
    """Helper to post a new Slack message in a thread."""
    from posthog.models.integration import SlackIntegration

    blocks = _build_slack_message_blocks(text, conversation_url)
    slack = SlackIntegration(integration)
    try:
        slack.client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text, blocks=blocks)
    except Exception as e:
        logger.exception("slack_message_post_failed", error=str(e))


async def _update_slack_message(
    integration: "Integration",
    channel: str,
    ts: str,
    text: str,
    conversation_url: str | None = None,
) -> None:
    """Helper to update a Slack message."""
    from posthog.models.integration import SlackIntegration

    blocks = _build_slack_message_blocks(text, conversation_url)
    slack = SlackIntegration(integration)
    try:
        slack.client.chat_update(channel=channel, ts=ts, text=text, blocks=blocks)
    except Exception as e:
        logger.exception("slack_message_update_failed", error=str(e))


async def _delete_slack_message(
    integration: "Integration",
    channel: str,
    ts: str,
) -> None:
    """Helper to delete a Slack message."""
    from posthog.models.integration import SlackIntegration

    slack = SlackIntegration(integration)
    try:
        slack.client.chat_delete(channel=channel, ts=ts)
    except Exception as e:
        logger.exception("slack_message_delete_failed", error=str(e))


async def _add_slack_reaction(
    integration: "Integration",
    channel: str,
    timestamp: str,
    name: str,
) -> None:
    """Helper to add a reaction to a Slack message."""
    from posthog.models.integration import SlackIntegration

    slack = SlackIntegration(integration)
    try:
        slack.client.reactions_add(channel=channel, timestamp=timestamp, name=name)
    except Exception as e:
        logger.exception("slack_reaction_add_failed", error=str(e))


async def _remove_slack_reaction(
    integration: "Integration",
    channel: str,
    timestamp: str,
    name: str,
) -> None:
    """Helper to remove a reaction from a Slack message."""
    from posthog.models.integration import SlackIntegration

    slack = SlackIntegration(integration)
    try:
        slack.client.reactions_remove(channel=channel, timestamp=timestamp, name=name)
    except Exception as e:
        logger.exception("slack_reaction_remove_failed", error=str(e))


async def _get_slack_workspace_domain(integration: "Integration") -> str | None:
    """Fetch the Slack workspace domain (subdomain) using team.info API."""
    from posthog.models.integration import SlackIntegration

    slack = SlackIntegration(integration)
    try:
        response = slack.client.team_info()
        if response.get("ok"):
            team = response.get("team")
            if isinstance(team, dict):
                return team.get("domain")
    except Exception as e:
        logger.exception("slack_team_info_failed", error=str(e))
    return None
