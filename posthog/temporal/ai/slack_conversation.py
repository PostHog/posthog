import json
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.ai.base import AgentBaseWorkflow

if TYPE_CHECKING:
    from posthog.models.integration import Integration

logger = structlog.get_logger(__name__)

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
    messages: list[dict[str, Any]]
    conversation_id: str


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
    from posthog.models.organization import OrganizationMembership

    from ee.hogai.chat_agent.runner import ChatAgentRunner
    from ee.models import Conversation

    team = await Team.objects.aget(id=inputs.team_id)
    integration = await Integration.objects.aget(id=inputs.integration_id)

    # Get a user from the team to run the agent as (use a team member)
    membership = (
        await OrganizationMembership.objects.filter(organization_id=team.organization_id)
        .select_related("user")
        .afirst()
    )
    if not membership or not membership.user:
        logger.error("slack_conversation_no_user", team_id=inputs.team_id)
        await _update_slack_message(
            integration,
            inputs.channel,
            inputs.initial_message_ts,
            "Sorry, I couldn't process your request - no team user found.",
        )
        return

    user: User = membership.user

    # Join all Slack messages into a single HumanMessage
    message_texts = []
    for msg in inputs.messages:
        username = msg.get("user", "Unknown")
        text = msg.get("text", "")
        message_texts.append(f"{username}: {text}")

    combined_message = "\n".join(message_texts)
    human_message = HumanMessage(content=combined_message)

    # Create a new conversation for this Slack thread with the pre-generated ID
    # Use aget_or_create in case the activity retries
    conversation, _ = await Conversation.objects.aget_or_create(
        id=inputs.conversation_id,
        defaults={"team": team, "user": user, "type": "slack"},
    )

    assistant = ChatAgentRunner(
        team,
        conversation,
        new_message=human_message,
        user=user,
        is_new_conversation=True,
    )

    # Collect all messages from the stream
    assistant_messages: list[AssistantMessage] = []
    artifact_messages: list[ArtifactMessage] = []

    async for _event_type, message in assistant.astream():
        if isinstance(message, AssistantMessage):
            assistant_messages.append(message)
        elif isinstance(message, ArtifactMessage):
            artifact_messages.append(message)
        activity.heartbeat()

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
        queries_section = "\n\nQueries:\n" + "\n".join(f"- <{url}|{title}>" for title, url in generated_queries)
        final_response += queries_section

    # Build conversation URL for the "View in PostHog" button
    conversation_url = f"{settings.SITE_URL}/project/{team.id}/ai?chat={inputs.conversation_id}"

    # Update the initial Slack message with the final response
    if final_response:
        await _update_slack_message(
            integration,
            inputs.channel,
            inputs.initial_message_ts,
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
        await _update_slack_message(
            integration,
            inputs.channel,
            inputs.initial_message_ts,
            "Sorry, I couldn't generate a response. Please try again.",
            conversation_url=conversation_url,
        )


async def _update_slack_message(
    integration: "Integration",
    channel: str,
    ts: str,
    text: str,
    conversation_url: str | None = None,
) -> None:
    """Helper to update a Slack message."""
    from posthog.models.integration import SlackIntegration

    # Split text into separate blocks per paragraph to avoid Slack's "See more..." truncation
    blocks: list[dict] = []

    # Split on double newlines (paragraph boundaries)
    paragraphs = text.split("\n\n")

    for para in paragraphs:
        if para.strip():  # Skip empty paragraphs
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": para}})

    if conversation_url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View in PostHog", "emoji": True},
                        "url": conversation_url,
                    }
                ],
            }
        )

    slack = SlackIntegration(integration)
    try:
        slack.client.chat_update(channel=channel, ts=ts, text=text, blocks=blocks)
    except Exception as e:
        logger.exception("slack_message_update_failed", error=str(e))
