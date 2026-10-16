"""Celery tasks for commands."""

from celery import shared_task

from ..channels.github.comments import dispatch_comment_command
from ..channels.github.intake import CommentCommandRequest
from ..channels.slack.mentions import SlackCommandRequest, dispatch_slack_command


# No retries: a command that fails tells the commenter so in a reply, and a silent second attempt
# could start a run they already gave up on.
@shared_task(ignore_result=True, max_retries=0)
def run_comment_command(
    *,
    installation_id: str,
    repository: str,
    pr_number: int,
    comment_id: int,
    comment_url: str,
    commenter_github_id: int,
    commenter_login: str,
    verb: str,
    argument: str,
    ambiguous: bool,
) -> None:
    dispatch_comment_command(
        CommentCommandRequest(
            installation_id=installation_id,
            repository=repository,
            pr_number=pr_number,
            comment_id=comment_id,
            comment_url=comment_url,
            commenter_github_id=commenter_github_id,
            commenter_login=commenter_login,
            verb=verb,
            argument=argument,
            ambiguous=ambiguous,
        )
    )


@shared_task(ignore_result=True, max_retries=0)
def run_slack_command(
    *,
    installation_id: str,
    team_ids: list[int],
    repository: str,
    pr_number: int,
    verb: str,
    argument: str,
    slack_team_id: str,
    slack_user_id: str,
    channel: str,
    thread_ts: str,
    message_ts: str,
    integration_id: int,
    integration_team_id: int,
    user_ids: list[int],
) -> None:
    dispatch_slack_command(
        SlackCommandRequest(
            installation_id=installation_id,
            team_ids=tuple(team_ids),
            repository=repository,
            pr_number=pr_number,
            verb=verb,
            argument=argument,
            slack_team_id=slack_team_id,
            slack_user_id=slack_user_id,
            channel=channel,
            thread_ts=thread_ts,
            message_ts=message_ts,
            integration_id=integration_id,
            integration_team_id=integration_team_id,
            user_ids=tuple(user_ids),
        )
    )
