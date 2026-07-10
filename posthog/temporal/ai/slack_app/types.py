"""Shared dataclasses for PostHog Slack App Temporal workflows.

Living here (and not in the workflow modules) so activities split into this
package can take the inputs dataclass as their typed signature without
creating an import cycle with the workflow modules.
"""

from dataclasses import dataclass, field, fields
from typing import Any, Literal

from pydantic import BaseModel


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
    # True when the message was dispatched to the per-conversation queue
    # workflow (slack-app-queue-workflow flag). Gates per-message identity:
    # the sandbox JWT and credential rebinds follow the message's actor
    # instead of the task creator. The legacy per-message workflow leaves
    # this False and keeps creator-bound credentials throughout.
    per_message_identity: bool = False


def coerce_mention_workflow_inputs(inputs: object) -> PostHogCodeSlackMentionWorkflowInputs:
    """Normalise an activity's ``inputs`` back into the dataclass.

    Temporal's default converter rebuilds the dataclass from the activity's type
    hint, but during a rolling deploy workers can briefly disagree on the
    activity signature and a payload arrives as a raw ``dict``. Reading
    ``inputs.integration_id`` on a dict then raises an opaque ``AttributeError``
    deep in the body. Rebuilding here keeps the flow working across version skew,
    and unknown keys are dropped so a newer sender's extra field doesn't blow up
    an older activity. A payload missing the required fields fails loudly with
    context instead of surfacing as an ``AttributeError``.
    """
    if isinstance(inputs, PostHogCodeSlackMentionWorkflowInputs):
        return inputs
    if isinstance(inputs, dict):
        known = {f.name for f in fields(PostHogCodeSlackMentionWorkflowInputs)}
        try:
            return PostHogCodeSlackMentionWorkflowInputs(**{k: v for k, v in inputs.items() if k in known})
        except TypeError as e:
            raise TypeError(
                "Could not coerce activity inputs into PostHogCodeSlackMentionWorkflowInputs "
                f"(keys={sorted(inputs)}): {e}"
            ) from e
    raise TypeError(
        f"Unexpected activity inputs type {type(inputs).__name__}; "
        "expected PostHogCodeSlackMentionWorkflowInputs or dict"
    )


@dataclass
class SlackAppMentionWorkflowInputs:
    """Conversation-level inputs for the per-thread queue workflow.

    One workflow instance covers one Slack conversation (channel thread or DM
    thread), identified entirely by its workflow ID; individual messages
    arrive as ``new_message`` signals carrying
    ``PostHogCodeSlackMentionWorkflowInputs``. These fields exist only to
    carry state across ``continue_as_new`` — fresh starts leave them empty.
    """

    pending_messages: list[PostHogCodeSlackMentionWorkflowInputs] = field(default_factory=list)
    processed_event_keys: list[str] = field(default_factory=list)


# The queue-ack reaction contract: the webhook adds the queued reaction at
# dispatch and the queue workflow swaps it for the processing one. Both sides
# must agree, so the names live here rather than as literals at each call site.
SLACK_APP_QUEUED_REACTION = "hourglass"
SLACK_APP_PROCESSING_REACTION = "eyes"


class MarkSlackAppMessageProcessingInput(BaseModel):
    """Single-argument input for ``mark_slack_app_message_processing_activity``.

    New Slack-app activities take one pydantic model instead of positional
    arguments so the payload can grow fields without signature churn.
    """

    integration_id: int
    slack_team_id: str
    channel: str
    message_ts: str


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
