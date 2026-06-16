from posthog.temporal.ai.anomaly_investigation import AnomalyInvestigationWorkflow, investigate_anomaly_activity
from posthog.temporal.ai.chat_agent import (
    AssistantConversationRunnerWorkflow,
    ChatAgentWorkflow,
    process_chat_agent_activity,
    process_conversation_activity,
)
from posthog.temporal.ai.posthog_code_slack_interactivity import (
    PostHogCodeSlackTerminateTaskWorkflow,
    process_posthog_code_terminate_task_activity,
)
from posthog.temporal.ai.research_agent import ResearchAgentWorkflow, process_research_agent_activity
from posthog.temporal.ai.slack_app import SLACK_APP_ACTIVITIES
from posthog.temporal.ai.slack_app.posthog_code_slack_mention import PostHogCodeSlackMentionWorkflow
from posthog.temporal.ai.slack_app.posthog_code_slack_mention_command import PostHogCodeSlackMentionCommandWorkflow
from posthog.temporal.ai.slack_conversation import (
    SlackConversationRunnerWorkflow,
    SlackConversationRunnerWorkflowInputs,
    process_slack_conversation_activity,
)

from .llm_traces_summaries.summarize_traces import (
    SummarizeLLMTracesInputs,
    SummarizeLLMTracesWorkflow,
    summarize_llm_traces_activity,
)
from .sync_vectors import (
    SyncVectorsInputs,
    SyncVectorsWorkflow,
    batch_embed_and_sync_actions,
    batch_summarize_actions,
    get_approximate_actions_count,
)

AI_WORKFLOWS = [
    SyncVectorsWorkflow,
    AssistantConversationRunnerWorkflow,
    ChatAgentWorkflow,
    ResearchAgentWorkflow,
    SummarizeLLMTracesWorkflow,
    SlackConversationRunnerWorkflow,
    PostHogCodeSlackMentionWorkflow,
    PostHogCodeSlackMentionCommandWorkflow,
    PostHogCodeSlackTerminateTaskWorkflow,
    AnomalyInvestigationWorkflow,
]

AI_ACTIVITIES = [
    get_approximate_actions_count,
    batch_summarize_actions,
    batch_embed_and_sync_actions,
    process_conversation_activity,
    process_chat_agent_activity,
    process_research_agent_activity,
    summarize_llm_traces_activity,
    process_slack_conversation_activity,
    *SLACK_APP_ACTIVITIES,
    process_posthog_code_terminate_task_activity,
    investigate_anomaly_activity,
]

__all__ = [
    "SyncVectorsInputs",
    "SummarizeLLMTracesInputs",
    "SlackConversationRunnerWorkflowInputs",
]
