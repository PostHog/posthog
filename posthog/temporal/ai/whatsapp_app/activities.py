from typing import Any

import structlog
from temporalio import activity

from posthog.temporal.ai.slack_app.types import PostHogCodeRepoCascadeOutcome
from posthog.temporal.ai.whatsapp_app.types import WhatsAppAppMentionWorkflowInputs
from posthog.temporal.common.utils import close_db_connections

logger = structlog.get_logger(__name__)

_WHATSAPP_DELIVERY_CONSTRAINTS = """WhatsApp delivery constraints:
- Your replies are delivered to a WhatsApp chat as plain text. Do not rely on
  markdown rendering, tables, or code blocks for meaning; keep formatting simple.
- Interactive pickers are not rendered in WhatsApp. When you need input from the
  user, ask in prose and continue when they reply.
- Do not create canvases, file artifacts, or other rich deliverables; summarize
  results directly in your reply and link to PostHog or GitHub for details."""


def _load_whatsapp_integration(inputs: WhatsAppAppMentionWorkflowInputs) -> Any:
    from posthog.models.integration import (
        Integration,  # noqa: PLC0415 — activity-body import, matches slack_app pattern
    )

    return Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="whatsapp",
        integration_id=inputs.wa_id,
    )


def _message_text(inputs: WhatsAppAppMentionWorkflowInputs) -> str:
    return str(((inputs.message.get("text") or {}).get("body")) or "").strip()


@activity.defn
@close_db_connections
def enforce_whatsapp_billing_quota_activity(inputs: WhatsAppAppMentionWorkflowInputs) -> bool:
    """True when the team is out of AI credits. Posting the denial is the workflow's
    job (via the generic reply activity) so the copy lives in one place."""
    from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited  # noqa: PLC0415

    integration = _load_whatsapp_integration(inputs)
    return bool(
        is_team_limited(
            integration.team.api_token,
            QuotaResource.AI_CREDITS,
            QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
        )
    )


@activity.defn
@close_db_connections
def post_whatsapp_reply_activity(inputs: WhatsAppAppMentionWorkflowInputs, text: str) -> None:
    from products.slack_app.backend.providers import ConversationRef, WhatsAppChatProvider  # noqa: PLC0415

    integration = _load_whatsapp_integration(inputs)
    provider = WhatsAppChatProvider(integration)
    provider.post_message(
        ConversationRef(channel_id=inputs.wa_id, thread_id=inputs.message_wamid),
        text,
    )


@activity.defn
@close_db_connections
def cascade_whatsapp_repository_activity(inputs: WhatsAppAppMentionWorkflowInputs) -> PostHogCodeRepoCascadeOutcome:
    """Synchronous fast-path repo resolution, mirroring the Slack cascade: no repos,
    exactly one, or an explicit ``org/repo`` in the message. Anything richer returns
    ``agent_needed`` — WhatsApp v1 has no picker or discovery agent, so the workflow
    answers with an ask-for-explicit-repo reply instead."""
    from posthog.models.integration import Integration  # noqa: PLC0415

    from products.slack_app.backend.api import _extract_explicit_repo, _get_full_repo_names  # noqa: PLC0415
    from products.slack_app.backend.feature_flags import is_slack_app_bot_prs_enabled  # noqa: PLC0415

    integration = _load_whatsapp_integration(inputs)
    all_repos = _get_full_repo_names(integration, user_id=inputs.user_id)

    if not all_repos:
        team_has_github = Integration.objects.filter(
            team=integration.team, kind=Integration.IntegrationKind.GITHUB
        ).exists()
        if team_has_github and not is_slack_app_bot_prs_enabled(integration.team):
            return PostHogCodeRepoCascadeOutcome(mode="needs_user_github", repository=None, reason="no_user_repos")
        return PostHogCodeRepoCascadeOutcome(mode="no_repo", repository=None, reason="no_repos")

    if len(all_repos) == 1:
        return PostHogCodeRepoCascadeOutcome(mode="auto", repository=all_repos[0], reason="single_repo")

    explicit_repo = _extract_explicit_repo(_message_text(inputs), all_repos)
    if explicit_repo:
        return PostHogCodeRepoCascadeOutcome(mode="auto", repository=explicit_repo, reason="explicit_mention")

    return PostHogCodeRepoCascadeOutcome(mode="agent_needed", repository=None, reason="needs_agent")


@activity.defn
@close_db_connections
def classify_whatsapp_task_needs_repo_activity(inputs: WhatsAppAppMentionWorkflowInputs) -> bool:
    """Whether the message needs code repository access, via the shared classifier.

    Biased toward False (like the other surfaces): answering an analytics ask with a
    no-repo task is recoverable, while demanding a repo for every question dead-ends
    the chat. WhatsApp has no readable thread history, so the message stands alone.
    """
    from posthog.temporal.ai.slack_app.activities.classifiers import classify_task_needs_repo  # noqa: PLC0415

    return classify_task_needs_repo(_message_text(inputs), [])


@activity.defn
@close_db_connections
def create_whatsapp_task_activity(inputs: WhatsAppAppMentionWorkflowInputs, repository: str | None) -> None:
    from products.slack_app.backend.models import WhatsAppChatTaskMapping  # noqa: PLC0415
    from products.slack_app.backend.providers import ConversationRef, WhatsAppChatProvider  # noqa: PLC0415
    from products.slack_app.backend.whatsapp_thread import WhatsAppThreadContext  # noqa: PLC0415
    from products.tasks.backend.facade import api as tasks_facade  # noqa: PLC0415
    from products.tasks.backend.facade.temporal import execute_task_processing_workflow  # noqa: PLC0415

    integration = _load_whatsapp_integration(inputs)
    root_message_id = inputs.message_wamid
    conversation = ConversationRef(channel_id=inputs.wa_id, thread_id=root_message_id)
    provider = WhatsAppChatProvider(integration)

    # Idempotency guard: a retry after the mapping write must not create a second
    # task for the same originating message (same rationale as the Slack activity).
    if (
        WhatsAppChatTaskMapping.objects.for_team(integration.team_id)
        .filter(integration_id=integration.id, wa_id=inputs.wa_id, root_message_id=root_message_id)
        .exists()
    ):
        logger.info(
            "slack_app_whatsapp_task_creation_skipped_existing_mapping",
            wa_id=inputs.wa_id,
            root_message_id=root_message_id,
            integration_id=integration.id,
        )
        return

    user_text = _message_text(inputs)
    title = user_text[:255] if user_text else "Task from WhatsApp"
    description = "\n\n".join([_WHATSAPP_DELIVERY_CONSTRAINTS, user_text])

    context = WhatsAppThreadContext(
        integration_id=integration.id,
        wa_id=inputs.wa_id,
        root_message_id=root_message_id,
    )

    try:
        created = tasks_facade.create_and_run_task(
            team=integration.team,
            title=title,
            description=description,
            origin_product=tasks_facade.TaskOriginProduct.WHATSAPP,
            user_id=inputs.user_id,
            repository=repository,
            create_pr=True,
            mode="interactive",
            slack_thread_context=context,
            interaction_origin="whatsapp",
            start_workflow=False,
            posthog_mcp_scopes="full",
            initial_permission_mode="bypassPermissions",
        )
    except Exception as e:
        logger.exception(
            "slack_app_whatsapp_task_creation_failed",
            error=str(e),
            team_id=integration.team_id,
            wa_id=inputs.wa_id,
        )
        try:
            provider.post_message(
                conversation, "Sorry, something went wrong creating the task. Please try again in a minute."
            )
        except Exception:
            logger.warning("slack_app_whatsapp_error_notification_failed", wa_id=inputs.wa_id)
        return

    task_run = created.latest_run
    if task_run is None:
        return

    # Mapping BEFORE starting the workflow so relayed output never races a missing row.
    WhatsAppChatTaskMapping.objects.for_team(integration.team_id).update_or_create(
        integration_id=integration.id,
        wa_id=inputs.wa_id,
        root_message_id=root_message_id,
        defaults={
            "team": integration.team,
            "task_id": created.task_id,
            "task_run_id": task_run.id,
        },
    )

    provider.add_reaction(conversation, root_message_id, "eyes")
    try:
        provider.post_message(conversation, "On it. I'll reply here when there's something to show.")
    except Exception:
        logger.warning("slack_app_whatsapp_ack_failed", wa_id=inputs.wa_id)

    execute_task_processing_workflow(
        task_id=str(created.task_id),
        run_id=str(task_run.id),
        team_id=created.team_id,
        user_id=inputs.user_id,
        create_pr=True,
        slack_thread_context=context,
        posthog_mcp_scopes="full",
    )
