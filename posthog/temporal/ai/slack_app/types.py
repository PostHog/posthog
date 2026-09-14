"""Shared dataclasses for PostHog Slack App Temporal workflows.

Living here (and not in the workflow modules) so activities split into this
package can take the inputs dataclass as their typed signature without
creating an import cycle with the workflow modules.
"""

from dataclasses import dataclass, field, fields
from typing import Any, Literal

from pydantic import BaseModel

from posthog.dataclasses import frozen


@dataclass
class PostHogSlackInboxOnboardingInputs:
    integration_id: int


@frozen
class SlackAppForkThreadInputs:
    """The Slack interactivity payload behind a "Fork to DM" click, verbatim.

    Passed through rather than parsed at the boundary: the webhook's only job is to ack
    inside Slack's three-second budget, so everything it could read from the payload is
    read in the activity instead.
    """

    payload: dict[str, Any]


@frozen
class PostHogCodeSlackMentionWorkflowInputs:
    event: dict[str, Any]
    integration_id: int
    slack_team_id: str
    # Resolved at routing time: dispatch never reaches this workflow without a
    # PostHog user, on either the ``app_mention`` or the untagged-reply path.
    user_id: int
    # Event that dispatched the workflow
    slack_event_id: str | None = None
    # True when the workflow was started for an untagged thread reply (event type
    # ``message``) rather than an explicit ``app_mention``. The routing layer
    # already verified a ``SlackThreadTaskMapping`` exists before dispatch, but
    # if the mapping is gone by the time the followup activity runs (race with
    # cleanup), we must NOT fall through to the new-task path — the user never
    # tagged us, so kicking off a brand-new agent run would be wrong.
    untagged_followup: bool = False
    # True when the thread's author already confirmed this untagged reply from the
    # ephemeral prompt. The classifier ran before the prompt was posted and the
    # answer is in, so the run skips both on the way back through.
    untagged_followup_confirmed: bool = False
    # Slack sets this on the event envelope for Slack Connect channels. It is
    # threaded through to task run state so customer-facing Slack replies remain
    # approval-gated even when a user's internal-write tier is full-auto.
    is_ext_shared_channel: bool = False
    # Set only on a forked run. The workflow
    # runs against a DM thread — that pair owns the task, the mapping, the answer
    # and every follow-up — but reads its `<slack_thread_context>` from the channel
    # thread the user forked, which these two point at. Unset everywhere else, so
    # the two pairs coincide and the fork branch is invisible.
    fork_source_channel: str | None = None
    fork_source_thread_ts: str | None = None
    # The message the reader forked from. The context block stops here: what was said
    # in the thread afterwards is not what they were looking at when they forked.
    fork_source_message_ts: str | None = None
    # The forked thread's own task, when it had one. Named in the context block so the
    # agent can pull that task's runs, logs and artifacts if the question needs more
    # than the messages.
    fork_source_task_id: str | None = None


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


# The queue reaction contract: the queue workflow adds the queued reaction to
# a message that has to wait behind another, then swaps it for the processing
# one when the message's turn starts. A message processed immediately gets
# only the processing reaction. Both activities must agree, so the names live
# here rather than as literals at each call site.
SLACK_APP_QUEUED_REACTION = "hourglass"
SLACK_APP_PROCESSING_REACTION = "eyes"


class SlackAppMessageReactionInput(BaseModel):
    """Single-argument input for the queue-reaction activities.

    New Slack-app activities take one pydantic model instead of positional
    arguments so the payload can grow fields without signature churn.
    """

    integration_id: int
    slack_team_id: str
    channel: str
    message_ts: str


class SlackAppModelOverrideInput(BaseModel):
    """Single-argument input for the model-override classifier activity."""

    integration_id: int
    slack_team_id: str
    event_text: str


class SlackAppModelOverride(BaseModel):
    """A per-task model choice read out of the mention text.

    ``model`` is always a live catalogue id (the classifier picks from a list and
    the activity drops anything that isn't on it); ``reasoning_effort`` is a known
    effort value that still has to be checked against whichever model the task ends
    up on. Either field may be absent — "run this with max effort" names no model,
    "use fable" names no effort. The merge onto the resolved preferences happens at
    the point of use, in ``resolve_run_preferences``.
    """

    model: str | None = None
    reasoning_effort: str | None = None


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


@frozen
class PostHogCodeRepoCascadeOutcome:
    """Synchronous fast-path repo resolution before the discovery agent runs.

    `auto` → use `repository` directly. `no_repo` → the mentioning user resolves no
    repos, so the mention becomes a repo-less task and the agent decides whether the
    ask needs code. `agent_needed` → there are multiple candidates and no explicit
    mention.
    """

    mode: Literal["auto", "no_repo", "agent_needed"]
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
