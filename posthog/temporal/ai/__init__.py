from posthog.temporal.ai.anomaly_investigation import AnomalyInvestigationWorkflow, investigate_anomaly_activity
from posthog.temporal.ai.chat_agent import (
    AssistantConversationRunnerWorkflow,
    ChatAgentWorkflow,
    process_chat_agent_activity,
    process_conversation_activity,
)
from posthog.temporal.ai.research_agent import ResearchAgentWorkflow, process_research_agent_activity
from posthog.temporal.ai.slack_app import SLACK_APP_ACTIVITIES
from posthog.temporal.ai.slack_app.posthog_code_slack_interactivity import (
    PostHogCodeSlackTerminateTaskWorkflow,
    process_posthog_code_terminate_task_activity,
)
from posthog.temporal.ai.slack_app.posthog_code_slack_mention import PostHogCodeSlackMentionWorkflow
from posthog.temporal.ai.slack_app.posthog_code_slack_mention_command import PostHogCodeSlackMentionCommandWorkflow
from posthog.temporal.ai.slack_app.posthog_slack_inbox_onboarding import PostHogSlackInboxOnboardingWorkflow
from posthog.temporal.ai.slack_conversation import (
    SlackConversationRunnerWorkflow,
    SlackConversationRunnerWorkflowInputs,
    process_slack_conversation_activity,
)

from products.pulse.backend.temporal import (
    PulseScanDispatcherInputs,
    PulseScanDispatcherWorkflow,
    PulseScanInputs,
    PulseScanWorkflow,
    create_or_get_digest_activity,
    emit_pulse_events_activity,
    enrich_findings_activity,
    fetch_findings_activity,
    list_eligible_team_ids_activity,
    load_scan_config_activity,
    notify_digest_activity,
    persist_findings_activity,
    reconcile_stale_digests_activity,
    set_digest_status_activity,
    set_workflow_run_id_activity,
    synthesize_digest_activity,
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

# PostHog Code Slack workflows live on TASKS_TASK_QUEUE alongside ProcessTaskWorkflow,
# the worker they hand off to once a repo is picked. The subset is kept exported so
# start_temporal_worker can register it on that queue without pulling in unrelated AI
# workflows.
POSTHOG_CODE_SLACK_WORKFLOWS = [
    PostHogCodeSlackMentionWorkflow,
    PostHogCodeSlackMentionCommandWorkflow,
    PostHogCodeSlackTerminateTaskWorkflow,
    PostHogSlackInboxOnboardingWorkflow,
]

POSTHOG_CODE_SLACK_ACTIVITIES = [
    *SLACK_APP_ACTIVITIES,
    process_posthog_code_terminate_task_activity,
]

AI_WORKFLOWS = [
    SyncVectorsWorkflow,
    AssistantConversationRunnerWorkflow,
    ChatAgentWorkflow,
    ResearchAgentWorkflow,
    SummarizeLLMTracesWorkflow,
    SlackConversationRunnerWorkflow,
    AnomalyInvestigationWorkflow,
    PulseScanWorkflow,
    PulseScanDispatcherWorkflow,
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
    investigate_anomaly_activity,
    fetch_findings_activity,
    enrich_findings_activity,
    persist_findings_activity,
    notify_digest_activity,
    emit_pulse_events_activity,
    synthesize_digest_activity,
    create_or_get_digest_activity,
    set_digest_status_activity,
    set_workflow_run_id_activity,
    load_scan_config_activity,
    list_eligible_team_ids_activity,
    reconcile_stale_digests_activity,
]

__all__ = [
    "SyncVectorsInputs",
    "SummarizeLLMTracesInputs",
    "SlackConversationRunnerWorkflowInputs",
    "PulseScanInputs",
    "PulseScanDispatcherInputs",
]
