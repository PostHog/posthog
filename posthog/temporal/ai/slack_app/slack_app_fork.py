"""Forking a channel thread into a DM.

Someone reading a thread wants to dig into it — understand the code, ask the
obvious question — without turning the thread into their own tutorial. Forking
opens a private DM that has already read the thread, and carries on there.

Reached three ways: the overflow menu under a reply, ``@PostHog fork [question]``
in the thread, and a message shortcut for anyone who registers one. All three
land here with the same payload shape.

Whether the run starts now turns on one thing — did the user say what they want?

- No question (the menu has nowhere to type one): the DM asks, and the run waits
  for the answer. The thread being forked is parked in ``fork_context`` so that
  answer can be resolved back to it, since a plain DM reply says nothing about
  where it came from.
- A question (``@PostHog fork why is this slow?``): there is nothing to wait for,
  so the run starts against it immediately.

The fork itself creates no agent machinery. It starts the ordinary mention
workflow against a DM thread, with ``fork_source_channel`` / ``fork_source_thread_ts``
telling that workflow to build its ``<slack_thread_context>`` from the channel
thread instead of the one it is answering in. Everything downstream — repo
selection, task creation, the thread mapping, streaming, follow-ups — is the
mention path untouched.

Posting the seed DM and dispatching live here rather than inside
``PostHogCodeSlackMentionWorkflow``: that workflow has live executions, so adding
commands to it would need a ``workflow.patched()`` gate, and this module is new.
"""

import json
from datetime import timedelta
from typing import Any

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.ai.slack_app.types import SlackAppForkThreadInputs
from posthog.temporal.common.base import PostHogWorkflow

logger = structlog.get_logger(__name__)

SLACK_APP_FORK_TIMEOUT_SECONDS = 5 * 60

# Long enough to recognise the thread, short enough to stay one line in a DM.
_TITLE_LIMIT = 120

FORK_THREAD_CALLBACK_ID = "posthog_fork_thread"

_SEED_UNAVAILABLE = (
    "I couldn't set that up — you don't seem to have a PostHog account matching your Slack email, "
    "or your projects have no connected repo."
)


@workflow.defn(name="slack-app-fork-thread")
class SlackAppForkThreadWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SlackAppForkThreadInputs:
        loaded = json.loads(inputs[0])
        return SlackAppForkThreadInputs(**loaded)

    @workflow.run
    async def run(self, inputs: SlackAppForkThreadInputs) -> None:
        await workflow.execute_activity(
            process_slack_app_fork_thread_activity,
            args=(inputs,),
            start_to_close_timeout=timedelta(seconds=SLACK_APP_FORK_TIMEOUT_SECONDS),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@activity.defn
def process_slack_app_fork_thread_activity(inputs: SlackAppForkThreadInputs) -> None:
    process_slack_app_fork_thread_payload(inputs.payload)


def build_fork_payload(
    *,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    slack_team_id: str,
    response_url: str | None = None,
    prompt: str | None = None,
) -> dict[str, Any]:
    """Shape a fork request the way the activity reads it.

    The activity was written against Slack's ``message_action`` payload; the
    ``/posthog fork`` and ``@PostHog fork`` surfaces synthesise the same shape
    rather than teach it a second one. Mirrors what the slash-command view does
    for the mention pipeline.

    ``prompt`` is the trailing text of ``fork <question>``. The menu and shortcut
    surfaces have nowhere to type one, so it stays ``None`` there and the DM asks
    for it instead of the run starting on a guess.
    """
    return {
        "channel": {"id": channel},
        "message": {"thread_ts": thread_ts, "ts": thread_ts},
        "user": {"id": slack_user_id},
        "team": {"id": slack_team_id},
        "response_url": response_url,
        "fork_prompt": prompt,
    }


def _ephemeral(response_url: str | None, text: str, *, slack: Any = None, **target: str) -> None:
    """Answer whoever asked, and only them.

    Forking must leave no trace in the source channel — half the point is asking
    a question you would rather not ask in front of everyone, so every outcome,
    including refusals, goes through here.

    ``chat.postEphemeral`` is preferred where we have a channel: it lands in the thread
    the fork came from, which is where the reader is looking, and it cannot disturb the
    message the menu is attached to.

    ``response_url`` is the fallback — it reaches surfaces the bot isn't a member of.
    ``replace_original`` is pinned false there because a response to an interactive
    message otherwise overwrites the message that carried the control, which for us is
    the agent's own answer.
    """
    if slack is not None and target.get("channel"):
        try:
            slack.client.chat_postEphemeral(
                channel=target["channel"],
                user=target.get("user", ""),
                thread_ts=target.get("thread_ts", ""),
                text=text,
            )
            return
        except Exception:
            logger.warning("slack_app_fork_ephemeral_post_failed")
    if not response_url:
        return
    import requests  # noqa: PLC0415 — keeps the HTTP dep off the module import path

    try:
        requests.post(
            response_url,
            json={"response_type": "ephemeral", "replace_original": False, "text": text},
            timeout=5,
        )
    except requests.RequestException:
        logger.warning("slack_app_fork_ephemeral_failed")


def process_slack_app_fork_thread_payload(payload: dict[str, Any]) -> None:
    from posthog.models.integration import SlackIntegration

    from products.slack_app.backend.analytics import capture_slack_event
    from products.slack_app.backend.api import SLACK_INTEGRATION_KIND, _channel_is_approved, _start_mention_workflow
    from products.slack_app.backend.feature_flags import is_slack_app_forking_enabled
    from products.slack_app.backend.models import SlackThreadTaskMapping
    from products.slack_app.backend.services.fork_context import PendingFork, store_pending_fork
    from products.slack_app.backend.services.integration_resolver import load_integrations, resolve_user_for_workspace
    from products.slack_app.backend.services.slack_messages import context_block

    source_channel = payload.get("channel", {}).get("id")
    message = payload.get("message", {}) or {}
    # Forking a reply forks the discussion it belongs to, not the single message —
    # "sidebar off this" always means the thread.
    source_thread_ts = message.get("thread_ts") or message.get("ts")
    slack_user_id = payload.get("user", {}).get("id")
    slack_team_id = payload.get("team", {}).get("id")
    response_url = payload.get("response_url")
    # `None` means nobody typed a question — the menu has nowhere to type one — which
    # is what makes the DM ask instead of guessing at an ask and running with it.
    fork_prompt = (payload.get("fork_prompt") or "").strip() or None

    if not (source_channel and source_thread_ts and slack_user_id and slack_team_id):
        logger.warning(
            "slack_app_fork_missing_payload_fields",
            has_channel=bool(source_channel),
            has_thread_ts=bool(source_thread_ts),
            has_user=bool(slack_user_id),
            has_team=bool(slack_team_id),
        )
        return

    logger.info(
        "slack_app_fork_requested",
        slack_team_id=slack_team_id,
        source_channel=source_channel,
        source_thread_ts=source_thread_ts,
    )

    workspace_result = load_integrations(
        slack_team_id=slack_team_id,
        kinds=[SLACK_INTEGRATION_KIND],
        slack_user_id=slack_user_id,
        channel=source_channel,
        thread_ts=source_thread_ts,
    )
    if not workspace_result.candidates:
        logger.info("slack_app_fork_refused", reason="no_candidates", slack_team_id=slack_team_id)
        return

    probe = workspace_result.resolved_or_first()
    # Where to speak when there is no ``response_url`` (the bare ``@PostHog fork``
    # mention). Built off the probe so refusals before project resolution can still
    # answer the asker.
    reply_to: dict[str, Any] = {"channel": source_channel, "thread_ts": source_thread_ts, "user": slack_user_id}
    if probe is None or not is_slack_app_forking_enabled(probe):
        # Outside the rollout the shortcut is inert rather than apologetic — a
        # workspace that never opted in should not learn the feature exists.
        logger.info("slack_app_fork_refused", reason="flag_off", slack_team_id=slack_team_id)
        return

    # The fork runs as whoever clicked, against a project *they* can reach — never
    # inherited from the source thread's original mentioner.
    resolution = resolve_user_for_workspace(
        workspace_result=workspace_result,
        slack_team_id=slack_team_id,
        slack_user_id=slack_user_id,
    )
    integration = resolution.integration or (resolution.candidates[0] if len(resolution.candidates) == 1 else None)
    if resolution.user is None or integration is None:
        logger.info(
            "slack_app_fork_refused",
            reason="user_unresolved" if resolution.user is None else "no_single_project",
            slack_team_id=slack_team_id,
        )
        _ephemeral(response_url, _SEED_UNAVAILABLE, slack=SlackIntegration(probe), **reply_to)
        return

    slack = SlackIntegration(integration)

    # A DM is never externally shared, so forking would otherwise launder content out
    # of a Slack Connect channel and past the approval gate that keeps customer-facing
    # writes gated. Refuse rather than fork-and-discover-later, and carry the flag
    # onto the run so the destination inherits the source's posture.
    is_ext_shared = _source_channel_is_ext_shared(slack, source_channel)
    if is_ext_shared and not _channel_is_approved(slack_team_id, source_channel):
        logger.info("slack_app_fork_refused", reason="ext_shared_unapproved", slack_team_id=slack_team_id)
        _ephemeral(
            response_url,
            "This is a Slack Connect channel that hasn't been approved for PostHog yet. "
            "`@PostHog` in the channel to approve it first, then fork.",
            slack=slack,
            **reply_to,
        )
        return

    # Without the bot in the channel, `conversations.replies` can't read the thread and
    # the fork would silently carry one message of context. Say so instead.
    thread_root = _read_thread_root(slack, source_channel, source_thread_ts)
    if thread_root is None:
        logger.info("slack_app_fork_refused", reason="bot_not_in_channel", slack_team_id=slack_team_id)
        _ephemeral(
            response_url,
            f"I can't read <#{source_channel}> — invite `@PostHog` to the channel and fork again "
            "and I'll pick up the whole thread.",
            slack=slack,
            **reply_to,
        )
        return

    # Inherit the repo the forked thread was already working on. A fork's prompt is
    # generic, so the cascade has nothing to match on and would send an "explain this
    # to me" ask to the discovery agent and then the repo picker, in a DM.
    # A thread the agent has already worked in has a task behind it, which holds far
    # more than the messages did: prior runs, session logs, artifacts, the PR. Carry
    # its id so the fork can go and read that when the question calls for it.
    source_task = (
        SlackThreadTaskMapping.objects.filter(
            integration=integration,
            channel=source_channel,
            thread_ts=source_thread_ts,
        )
        .values_list("task_id", "task__repository")
        .first()
    )
    source_task_id, fork_repository = (str(source_task[0]), source_task[1]) if source_task else (None, None)

    permalink = _thread_permalink(slack, source_channel, source_thread_ts)
    title = _fork_title(thread_root)
    lead = f":thread: *{title}*"
    body = (
        "I've read the thread. What do you want to dig into?"
        if fork_prompt is None
        else "On it :hourglass_flowing_sand:"
    )
    origin = f"Fork of <{permalink}|this thread>" if permalink else "Fork of a thread"
    seed_blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"{lead}\n{body}"}},
        context_block(f"{origin} in <#{source_channel}>"),
    ]

    try:
        seed = slack.client.chat_postMessage(
            channel=slack_user_id,
            text=f"{title} — {body}",
            blocks=seed_blocks,
            unfurl_links=False,
        )
    except Exception:
        logger.exception("slack_app_fork_seed_post_failed", slack_team_id=slack_team_id)
        _ephemeral(
            response_url,
            "I couldn't open a DM — check that you allow DMs from apps, then try again.",
            slack=slack,
            **reply_to,
        )
        return

    dm_channel = seed.get("channel")
    seed_ts = seed.get("ts")
    if not (dm_channel and seed_ts):
        logger.warning("slack_app_fork_seed_missing_ids", slack_team_id=slack_team_id)
        return

    if fork_prompt is None:
        # No question was typed — the menu has nowhere to type one — so the DM asks
        # rather than guessing, and the run waits for the answer. Park the pointer to
        # the forked thread so that answer can be resolved back to it; nothing else on
        # a plain DM reply says where it came from.
        store_pending_fork(
            integration.id,
            dm_channel,
            seed_ts,
            PendingFork(
                source_channel=source_channel,
                source_thread_ts=source_thread_ts,
                repository=fork_repository,
                task_id=source_task_id,
                is_ext_shared=is_ext_shared,
            ),
        )
    else:
        # `@PostHog fork <question>` already carries the ask, so there is nothing to
        # wait for. Mention-shaped so the existing pipeline takes it without
        # special-casing — the same trick the slash-command surface uses.
        _start_mention_workflow(
            {
                "type": "message",
                "channel": dm_channel,
                "ts": seed_ts,
                "thread_ts": seed_ts,
                "user": slack_user_id,
                "text": fork_prompt,
            },
            integration,
            slack_team_id,
            None,
            posthog_user=resolution.user,
            is_ext_shared_channel=is_ext_shared,
            fork_source_channel=source_channel,
            fork_source_thread_ts=source_thread_ts,
            fork_repository=fork_repository,
            fork_source_task_id=source_task_id,
        )

    logger.info(
        "slack_app_fork_created",
        slack_team_id=slack_team_id,
        team_id=integration.team_id,
        source_channel=source_channel,
        dm_channel=dm_channel,
        inherited_repository=bool(fork_repository),
    )
    _ephemeral(
        response_url,
        ":envelope_with_arrow: Forked to your DMs — check your messages with PostHog. Only you can see this.",
        slack=slack,
        **reply_to,
    )

    # Reported as its own event rather than folded into the mention funnel: a fork is a
    # different intent and would otherwise inflate mention counts.
    capture_slack_event(
        integration,
        "slack app fork created",
        slack_user_id=slack_user_id,
        source_channel=source_channel,
        is_ext_shared_channel=is_ext_shared,
        inherited_repository=bool(fork_repository),
    )


def _thread_permalink(slack: Any, channel: str, thread_ts: str) -> str | None:
    """Link back to the forked thread, or `None` if Slack won't give one.

    Best-effort: the fork works without it, the seed message just names the channel
    instead of linking it.
    """
    try:
        resp = slack.client.chat_getPermalink(channel=channel, message_ts=thread_ts)
        if resp.get("ok"):
            return resp["permalink"]
    except Exception:
        logger.warning("slack_app_fork_permalink_failed", channel=channel, thread_ts=thread_ts)
    return None


def _source_channel_is_ext_shared(slack: Any, channel: str) -> bool:
    """Whether the forked channel is a Slack Connect channel.

    Unlike events, interactivity payloads carry no ``is_ext_shared_channel`` on the
    envelope, so this costs a ``conversations.info`` round trip. Fails closed: an
    unreadable channel is treated as externally shared, which at worst asks the user
    to approve a channel that did not need it.
    """
    try:
        info = slack.client.conversations_info(channel=channel)
        conversation = info.get("channel", {}) or {}
        return bool(conversation.get("is_ext_shared") or conversation.get("is_pending_ext_shared"))
    except Exception:
        logger.warning("slack_app_fork_channel_info_failed", channel=channel)
        return True


def _read_thread_root(slack: Any, channel: str, thread_ts: str) -> dict[str, Any] | None:
    """The forked thread's opening message, or `None` if we can't read the thread.

    Doubles as the can-we-read-this check: the fork needs an answer to that anyway, and
    the same call returns the message the DM is titled after.
    """
    try:
        response = slack.client.conversations_replies(channel=channel, ts=thread_ts, limit=1)
    except Exception:
        logger.info("slack_app_fork_thread_unreadable", channel=channel, thread_ts=thread_ts)
        return None
    messages = response.get("messages") or []
    return messages[0] if messages else {}


def _fork_title(root: dict[str, Any]) -> str:
    """A one-line name for the thread, taken from the message that opened it.

    The DM needs to say *which* discussion it forked, and at this point no task exists
    to borrow a title from — the run doesn't start until the user says what they want.
    The opening message is what a reader would recognise the thread by.

    Falls back to a generic label for a thread that opens with a file, an image, or a
    bare mention: better an unhelpful title than an empty one.
    """
    from products.slack_app.backend.services.slack_messages import (  # noqa: PLC0415 — products import, deferred like the rest
        extract_message_text,
        labeled_mentions_to_display_names,
    )

    try:
        text = extract_message_text(root)
    except Exception:
        text = (root.get("text") or "").strip()
    first_line = next(
        (line.strip() for line in labeled_mentions_to_display_names(text).splitlines() if line.strip()), ""
    )
    if not first_line:
        return "Slack thread"
    return first_line if len(first_line) <= _TITLE_LIMIT else first_line[: _TITLE_LIMIT - 1].rstrip() + "…"
