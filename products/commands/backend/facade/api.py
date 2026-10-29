"""Facade for commands.

The ONLY module other products and core may import. It stays cheap to import, because the webhook
consumer calls it inside the request for every comment on every pull request.
"""

from __future__ import annotations

from collections.abc import Mapping

import structlog

from ..channels.github.intake import CommentCommandRequest, Dropped, read_comment_command
from ..channels.slack.parsing import may_hold_command as _may_hold_command
from .contracts import SlackMention

logger = structlog.get_logger(__name__)

__all__ = ["SlackMention", "accept_issue_comment", "accept_slack_mention", "may_hold_command"]


def accept_issue_comment(payload: Mapping[str, object]) -> None:
    """Queue the command in a verified ``issue_comment`` payload, if it holds one.

    Most comments are not commands and stop here without touching the database or the queue.
    """
    request = read_comment_command(payload)
    if isinstance(request, Dropped):
        if request.reason not in ("not_created", "not_pull_request", "no_command"):
            logger.info("github_command_dropped", reason=request.reason)
        return
    _enqueue(request)


def _enqueue(request: CommentCommandRequest) -> None:
    # Deferred: the task module imports every product facade a command dispatches into, and most
    # comments never get this far.
    from ..tasks.tasks import run_comment_command  # noqa: PLC0415

    run_comment_command.delay(
        installation_id=request.installation_id,
        repository=request.repository,
        pr_number=request.pr_number,
        comment_id=request.comment_id,
        comment_url=request.comment_url,
        commenter_github_id=request.commenter_github_id,
        commenter_login=request.commenter_login,
        verb=request.verb,
        argument=request.argument,
        ambiguous=request.ambiguous,
    )


def may_hold_command(text: str) -> bool:
    """False when a message names nothing a command acts on, so the caller can skip it for free.

    It runs no query, so a webhook that sees every message can call it first. True does not mean
    the message is a command: ``accept_slack_mention`` decides that.
    """
    return _may_hold_command(text)


def accept_slack_mention(mention: SlackMention) -> str | None:
    """Queue the command in a Slack mention, if it holds one, and return its verb.

    Runs inside the Slack webhook. None leaves the mention to the agent: free text, a mistyped
    command, or an organization outside the rollout.
    """
    # Deferred: the Slack channel imports the dispatcher, and the GitHub consumer imports this module
    # inside the request for every pull request comment.
    from ..channels.slack.mentions import read_slack_command  # noqa: PLC0415
    from ..logic.subjects import subject_payload  # noqa: PLC0415
    from ..tasks.tasks import run_slack_command  # noqa: PLC0415

    command = read_slack_command(mention)
    if command is None:
        return None
    run_slack_command.delay(
        subject=subject_payload(command.subject),
        team_ids=list(command.team_ids),
        verb=command.verb,
        argument=command.argument,
        slack_team_id=command.slack_team_id,
        slack_user_id=command.slack_user_id,
        channel=command.channel,
        thread_ts=command.thread_ts,
        message_ts=command.message_ts,
        integration_id=command.integration_id,
        integration_team_id=command.integration_team_id,
        user_ids=list(command.user_ids),
    )
    return command.verb
