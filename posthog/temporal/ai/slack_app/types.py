"""Shared dataclasses for PostHog Slack App Temporal workflows.

Living here (and not in the workflow modules) so activities split into this
package can take the inputs dataclass as their typed signature without
creating an import cycle with the workflow modules.
"""

from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class PostHogSlackInboxOnboardingInputs:
    integration_id: int


@dataclass
class PostHogCodeSlackMentionWorkflowInputs:
    event: dict[str, Any]
    integration_id: int
    slack_team_id: str
    # Event that dispatched the workflow
    slack_event_id: str | None = None
    # Resolved at routing time. ``None`` only on in-flight workflow histories
    # started before this field existed; those fall back to the in-workflow
    # resolve activity below. Remove the fallback (and this field's optionality)
    # once the workflow history retention window has elapsed.
    user_id: int | None = None
    # True when the workflow was started for an untagged thread reply (event type
    # ``message``) rather than an explicit ``app_mention``. The routing layer
    # already verified a ``SlackThreadTaskMapping`` exists before dispatch, but
    # if the mapping is gone by the time the followup activity runs (race with
    # cleanup), we must NOT fall through to the new-task path — the user never
    # tagged us, so kicking off a brand-new agent run would be wrong.
    untagged_followup: bool = False
    # Slack sets this on the event envelope for Slack Connect channels. It is
    # threaded through to task run state so customer-facing Slack replies remain
    # approval-gated even when a user's internal-write tier is full-auto.
    is_ext_shared_channel: bool = False


@dataclass
class PostHogCodeSlackMentionCommandWorkflowInputs:
    event: dict[str, Any]
    integration_ids: list[int]
    slack_team_id: str
    # Resolved at routing time on the mention path. The slash surface passes
    # ``None`` on purpose — it defers user resolution into the workflow's first
    # activity to keep its webhook ack under Slack's 3s budget — so the
    # in-workflow resolve fallback is permanent, not a legacy shim.
    user_id: int | None = None
    # The invoking surface's prefix, used verbatim in user-facing help/error copy:
    # ``@PostHog`` for mentions, ``/posthog`` for the slash command.
    command_prefix: str = "@PostHog"


@dataclass
class PostHogCodeRepoCascadeOutcome:
    """Synchronous fast-path repo resolution before the discovery agent runs.

    `auto` → use `repository` directly. `no_repo` → create a task with no repo
    (e.g. team has no GitHub integration connected). `agent_needed` → there are
    multiple candidates and no explicit mention. `needs_user_github` → the team
    has a GitHub install but the mentioning user has not connected their personal
    GitHub yet, so the workflow should fire the connect-GitHub prompt rather than
    silently creating a no-repo task.
    """

    mode: Literal["auto", "no_repo", "agent_needed", "needs_user_github"]
    repository: str | None
    reason: str


@dataclass
class SlackRepoSelectionOutcome:
    """Discovery-agent result wrapped at the activity boundary.

    `found` → use `repository`. `no_match` → no plausible candidate, create a
    no-repo task. `failed` → agent crashed/timed out/hallucinated, fall back to
    the interactive repo picker so the user can resolve manually.

    `repo_research_task_id`/`repo_research_run_id` point at the internal sandbox
    run the repo discovery agent spun up to make this call.
    """

    status: Literal["found", "no_match", "failed"]
    repository: str | None
    reason: str
    repo_research_task_id: str | None = None
    repo_research_run_id: str | None = None


@dataclass
class PostHogCodeRulesCommandResult:
    status: str  # "not_a_command" | "handled" | "needs_picker"
    pending_rule_text: str | None = None


@dataclass
class PostHogCodeSlackMentionCommandResult:
    """Outcome of the synchronous command-dispatch activity.

    ``status="done"`` means the command was handled (or refused) inline by the
    activity and the workflow has nothing left to do. ``status="needs_picker"``
    means the parsed command is a ``rules add`` without an inline repository,
    and the workflow must drive the interactive repo-picker flow against
    ``target_integration_id`` using ``pending_rule_text``.
    """

    status: str  # "done" | "needs_picker"
    pending_rule_text: str | None = None
    target_integration_id: int | None = None
