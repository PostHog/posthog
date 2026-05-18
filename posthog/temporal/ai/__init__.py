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
from posthog.temporal.ai.posthog_code_slack_mention import (
    PostHogCodeSlackMentionWorkflow,
    classify_posthog_code_task_needs_repo_activity,
    collect_posthog_code_thread_messages_activity,
    create_posthog_code_routing_rule_activity,
    create_posthog_code_task_for_repo_activity,
    forward_posthog_code_followup_activity,
    handle_posthog_code_rules_command_activity,
    post_posthog_code_internal_error_activity,
    post_posthog_code_no_repos_activity,
    post_posthog_code_picker_timeout_activity,
    post_posthog_code_repo_picker_activity,
    resolve_posthog_code_slack_user_activity,
    select_posthog_code_repository_activity,
)
from posthog.temporal.ai.research_agent import ResearchAgentWorkflow, process_research_agent_activity
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
    resolve_posthog_code_slack_user_activity,
    handle_posthog_code_rules_command_activity,
    collect_posthog_code_thread_messages_activity,
    create_posthog_code_routing_rule_activity,
    select_posthog_code_repository_activity,
    classify_posthog_code_task_needs_repo_activity,
    post_posthog_code_no_repos_activity,
    post_posthog_code_repo_picker_activity,
    create_posthog_code_task_for_repo_activity,
    forward_posthog_code_followup_activity,
    post_posthog_code_picker_timeout_activity,
    post_posthog_code_internal_error_activity,
    process_posthog_code_terminate_task_activity,
    investigate_anomaly_activity,
]

__all__ = [
    "SyncVectorsInputs",
    "SummarizeLLMTracesInputs",
    "SlackConversationRunnerWorkflowInputs",
]
