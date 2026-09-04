import asyncio
from typing import Any

import structlog
from temporalio import activity

from posthog.temporal.ai.slack_app.helpers import safe_react
from posthog.temporal.ai.slack_app.types import (
    PostHogCodeRepoCascadeOutcome,
    PostHogCodeSlackMentionWorkflowInputs,
    SlackRepoSelectionOutcome,
)
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.utils import close_db_connections

logger = structlog.get_logger(__name__)


@activity.defn
@close_db_connections
def cascade_posthog_code_repository_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    event_text: str,
    user_id: int,
    thread_messages: list[dict[str, str]] | None = None,
    mention_ts: str | None = None,
) -> PostHogCodeRepoCascadeOutcome:
    """Synchronous fast-path before the discovery agent.

    Resolves the trivial cases without paying for the sandbox-backed agent: no GitHub
    repos connected to the mentioning user's personal install, exactly one connected, or
    an explicit `org/repo` named in the mention or in the thread it sits in. Anything
    else returns `mode='agent_needed'` and the workflow takes over.

    The discovery agent this preempts reads the whole thread, so the fast path must too:
    a mention-only read sends every ask whose link sits in an earlier message to a
    sandbox run that then finds the repo in text the fast path skipped. Only messages at
    or before ``mention_ts`` may name the repo, though: the snapshot is taken when the
    activity runs, so it can contain replies posted after the mention, and letting those
    win the newest-first scan would let any channel participant redirect someone else's
    ask by pasting a repo link right after it.

    ``thread_messages`` and ``mention_ts`` default to ``None`` for backwards
    compatibility with calls recorded before the parameters existed: if a worker drains
    an activity task scheduled by an older workflow, the call still binds and degrades
    to the mention-only behavior.
    """
    from posthog.models.integration import Integration

    from products.slack_app.backend.api import _get_full_repo_names

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )
    all_repos = _get_full_repo_names(integration, user_id=user_id)

    if not all_repos:
        # No repos means no repo, whatever the team has installed. Deciding here that the user must
        # connect a personal install would gate the mention before anyone has asked whether it is
        # even about code; `no_repo` becomes a repo-less task instead, and the agent tells the user
        # to connect GitHub only once it can see that the ask needs code.
        return PostHogCodeRepoCascadeOutcome(mode="no_repo", repository=None, reason="no_repos")

    if len(all_repos) == 1:
        return PostHogCodeRepoCascadeOutcome(mode="auto", repository=all_repos[0], reason="single_repo")

    outcome = _resolve_explicit_repo(event_text, _messages_at_or_before(thread_messages or [], mention_ts), all_repos)
    # Logged so the share of mentions each resolution tier saves from the discovery agent is measurable.
    logger.info(
        "posthog_code_cascade_outcome",
        reason=outcome.reason,
        integration_id=inputs.integration_id,
    )
    return outcome


def _messages_at_or_before(messages: list[dict[str, str]], mention_ts: str | None) -> list[dict[str, str]]:
    """Messages eligible as repo-selection evidence: posted at or before the mention.

    Fail-closed on a missing bound — resolution degrades to the mention text alone —
    which is why this doesn't just call the shared helper: there, no bound means no clip.
    """
    from products.slack_app.backend.services.slack_messages import messages_at_or_before

    if not mention_ts:
        return []
    return messages_at_or_before(messages, mention_ts)


def _resolve_explicit_repo(
    event_text: str, thread_messages: list[dict[str, str]], all_repos: list[str]
) -> PostHogCodeRepoCascadeOutcome:
    """Repo named by the mention, then by the thread, each reported under its own reason."""
    from products.slack_app.backend.api import _extract_explicit_repo, _extract_explicit_repo_from_thread

    explicit_repo = _extract_explicit_repo(event_text, all_repos)
    if explicit_repo:
        return PostHogCodeRepoCascadeOutcome(mode="auto", repository=explicit_repo, reason="explicit_mention")

    thread_repo = _extract_explicit_repo_from_thread(thread_messages, all_repos)
    if thread_repo:
        return PostHogCodeRepoCascadeOutcome(mode="auto", repository=thread_repo, reason="explicit_thread_mention")

    return PostHogCodeRepoCascadeOutcome(mode="agent_needed", repository=None, reason="needs_agent")


@activity.defn
@close_db_connections
async def discover_posthog_code_repository_via_agent_activity(
    inputs: PostHogCodeSlackMentionWorkflowInputs,
    channel: str,
    event: dict[str, Any],
    thread_messages: list[dict[str, str]],
    user_id: int,
) -> SlackRepoSelectionOutcome:
    """Run the shared discovery agent and wrap its result for the workflow.

    Catches all exceptions internally (timeout, sandbox crash, validation
    reject from a hallucinated repo) and surfaces them as
    `status='failed'` so the workflow falls back to the interactive picker.
    The agent's legitimate "no plausible candidate" result becomes
    `status='no_match'`, which the workflow turns into a no-repo task.
    """
    from posthog.models.integration import Integration, SlackIntegration

    from products.tasks.backend.facade import api as tasks_facade
    from products.tasks.backend.facade.repo_selection import (
        RepoSelectionRejectedError,
        RepoSelectionUnavailableError,
        select_repository,
    )

    user_message_ts = event.get("ts")

    integration = await Integration.objects.select_related("team", "team__organization").aget(
        id=inputs.integration_id,
        kind="slack",
        integration_id=inputs.slack_team_id,
    )

    # Best-effort searching reaction so the user sees we're working before
    # the agent (which can take ~10–60s) finishes. Offloaded to a thread since
    # this is the only async activity in the file calling the sync Slack SDK.
    if user_message_ts:
        try:
            slack = SlackIntegration(integration)
            await asyncio.to_thread(safe_react, slack.client, channel, user_message_ts, "mag")
        except Exception:
            logger.warning("posthog_code_search_reaction_failed", channel=channel)

    # Render the Slack thread to a free-form context block for the generic
    # selector. The selector is domain-agnostic; the caller serializes.
    context_block = "\n".join(f"{msg['user']}: {msg['text']}" for msg in thread_messages)

    # Captured even when select_repository later raises
    research_ids: dict[str, str] = {}

    def _capture_research_session(task_id: str, run_id: str) -> None:
        research_ids["task_id"] = task_id
        research_ids["run_id"] = run_id

    try:
        async with Heartbeater():
            result = await select_repository(
                team_id=integration.team_id,
                user_id=user_id,
                context=context_block,
                origin_product=tasks_facade.TaskOriginProduct.SLACK,
                on_research_session=_capture_research_session,
            )
    except RepoSelectionRejectedError as exc:
        logger.warning(
            "posthog_code_repo_selection_rejected",
            channel=channel,
            returned_repository=exc.returned_repository,
            reason=exc.reason,
        )
        return SlackRepoSelectionOutcome(
            status="failed",
            repository=None,
            # Don't echo `exc.returned_repository` — it's raw LLM output and reaches Slack mrkdwn.
            reason="Agent returned an unrecognized repository.",
            repo_research_task_id=research_ids.get("task_id"),
            repo_research_run_id=research_ids.get("run_id"),
        )
    except RepoSelectionUnavailableError as exc:
        logger.warning(
            "posthog_code_repo_selection_unavailable",
            channel=channel,
            reason=exc.reason,
        )
        return SlackRepoSelectionOutcome(
            status="failed",
            repository=None,
            reason=f"Repo selection unavailable: {exc.reason}",
            repo_research_task_id=research_ids.get("task_id"),
            repo_research_run_id=research_ids.get("run_id"),
        )
    except Exception as exc:
        logger.exception(
            "posthog_code_repo_selection_failed",
            channel=channel,
            error=str(exc),
        )
        return SlackRepoSelectionOutcome(
            status="failed",
            repository=None,
            reason=f"Agent failed: {type(exc).__name__}",
            repo_research_task_id=research_ids.get("task_id"),
            repo_research_run_id=research_ids.get("run_id"),
        )

    if result.repository is None:
        return SlackRepoSelectionOutcome(
            status="no_match",
            repository=None,
            reason=result.reason,
            repo_research_task_id=research_ids.get("task_id"),
            repo_research_run_id=research_ids.get("run_id"),
        )
    return SlackRepoSelectionOutcome(
        status="found",
        repository=result.repository,
        reason=result.reason,
        repo_research_task_id=research_ids.get("task_id"),
        repo_research_run_id=research_ids.get("run_id"),
    )
