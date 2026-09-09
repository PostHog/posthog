"""The activity behind the "Fork to DM" menu.

Lives apart from the workflow, like every other Slack-app activity. See
``posthog.temporal.ai.slack_app.slack_app_fork`` for what a fork is and why the
run does not start here.
"""

from typing import Any

import structlog
from temporalio import activity

from posthog.temporal.ai.slack_app.types import SlackAppForkThreadInputs

logger = structlog.get_logger(__name__)

# Long enough to recognise the thread, short enough to stay one line in a DM.
_TITLE_LIMIT = 120

_SEED_UNAVAILABLE = (
    "I couldn't set that up — you don't seem to have a PostHog account matching your Slack email, "
    "or your projects have no connected repo."
)


@activity.defn
def process_slack_app_fork_thread_activity(inputs: SlackAppForkThreadInputs) -> None:
    process_slack_app_fork_thread_payload(inputs.payload)


def _ephemeral(slack: Any, text: str, *, channel: str, thread_ts: str, user: str, response_url: str | None) -> None:
    """Answer whoever asked, and only them.

    Forking must leave no trace in the source channel — half the point is asking a
    question you would rather not ask in front of everyone, so every outcome, including
    refusals, goes through here.

    An ephemeral post is preferred: it lands in the thread the reader is looking at and
    cannot disturb the message the menu hangs off. ``response_url`` is the fallback for
    a channel the bot isn't in, with ``replace_original`` pinned false — a reply to an
    interactive message otherwise overwrites the message carrying the control, which
    here is the agent's own answer.
    """
    from products.slack_app.backend.api import (
        _post_slack_user_ephemeral,  # noqa: PLC0415 — products import, deferred like the rest
    )

    if _post_slack_user_ephemeral(slack, channel, user, thread_ts, text):
        return
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
    from products.slack_app.backend.api import SLACK_INTEGRATION_KIND, _channel_is_approved
    from products.slack_app.backend.feature_flags import is_slack_app_forking_enabled
    from products.slack_app.backend.models import SlackThreadTaskMapping
    from products.slack_app.backend.services.integration_resolver import load_integrations, resolve_user_for_workspace
    from products.slack_app.backend.services.slack_fork_context import PendingFork, store_pending_fork
    from products.slack_app.backend.services.slack_messages import context_block, thread_permalink

    source_channel = payload.get("channel", {}).get("id")
    message = payload.get("message", {}) or {}
    # Forking a reply forks the discussion it belongs to, not the single message —
    # "sidebar off this" always means the thread.
    source_thread_ts = message.get("thread_ts") or message.get("ts")
    # The reply the menu hangs off. The thread is read up to here, so the fork carries
    # the discussion as it stood when the reader forked it.
    source_message_ts = message.get("ts") or source_thread_ts
    slack_user_id = payload.get("user", {}).get("id")
    slack_team_id = payload.get("team", {}).get("id")
    response_url = payload.get("response_url")

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
    # Every reply to the asker goes to the source thread, ephemerally. Built off the
    # probe so refusals before project resolution can still answer them.
    reply_to = {
        "channel": source_channel,
        "thread_ts": source_thread_ts,
        "user": slack_user_id,
        "response_url": response_url,
    }
    if probe is None or not is_slack_app_forking_enabled(probe):
        # Outside the rollout the menu is inert rather than apologetic — a
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
        _ephemeral(SlackIntegration(probe), _SEED_UNAVAILABLE, **reply_to)
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
            slack,
            "This is a Slack Connect channel that hasn't been approved for PostHog yet. "
            "`@PostHog` in the channel to approve it first, then fork.",
            **reply_to,
        )
        return

    # Without the bot in the channel, `conversations.replies` can't read the thread and
    # the fork would silently carry one message of context. Say so instead.
    thread_root = _read_thread_root(slack, source_channel, source_thread_ts)
    if thread_root is None:
        logger.info("slack_app_fork_refused", reason="bot_not_in_channel", slack_team_id=slack_team_id)
        _ephemeral(
            slack,
            f"I can't read <#{source_channel}> — invite `@PostHog` to the channel and fork again "
            "and I'll pick up the whole thread.",
            **reply_to,
        )
        return

    # A thread the agent has already worked in has a task behind it, holding far more
    # than the messages did: prior runs, session logs, artifacts, the PR. Carry its id
    # so the fork can read that when the question calls for it. Its repository is
    # deliberately not carried over: the fork runs the normal cascade, which resolves a
    # repo against what the *requester* can access rather than what the source thread's
    # mentioner could.
    source_task = (
        SlackThreadTaskMapping.objects.filter(
            integration=integration,
            channel=source_channel,
            thread_ts=source_thread_ts,
        )
        .values_list("task_id", flat=True)
        .first()
    )
    source_task_id = str(source_task) if source_task else None

    permalink = thread_permalink(slack, source_channel, source_thread_ts)
    title = _fork_title(thread_root)
    body = "I've read the thread. What do you want to dig into?"
    origin = f"Fork of <{permalink}|this thread>" if permalink else "Fork of a thread"
    seed_blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f":thread: *{title}*\n{body}"}},
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
            slack,
            "I couldn't open a DM — check that you allow DMs from apps, then try again.",
            **reply_to,
        )
        return

    dm_channel = seed.get("channel")
    seed_ts = seed.get("ts")
    if not (dm_channel and seed_ts):
        logger.warning("slack_app_fork_seed_missing_ids", slack_team_id=slack_team_id)
        return

    # The menu has nowhere to type a question, so the DM asks and the run waits for the
    # answer. Park the forked thread so that answer can be resolved back to it; nothing
    # else on a plain DM reply says where it came from.
    store_pending_fork(
        integration.id,
        dm_channel,
        seed_ts,
        PendingFork(
            source_channel=source_channel,
            source_thread_ts=source_thread_ts,
            source_message_ts=source_message_ts,
            task_id=source_task_id,
            is_ext_shared=is_ext_shared,
        ),
    )

    logger.info(
        "slack_app_fork_created",
        slack_team_id=slack_team_id,
        team_id=integration.team_id,
        source_channel=source_channel,
        dm_channel=dm_channel,
        has_source_task=bool(source_task_id),
    )
    _ephemeral(
        slack,
        ":envelope_with_arrow: Forked to your DMs — check your messages with PostHog. Only you can see this.",
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
        has_source_task=bool(source_task_id),
    )


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
