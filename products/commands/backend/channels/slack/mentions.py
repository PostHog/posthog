"""Commands from Slack mentions: what they act on, who may ask, and how the answer goes back.

The Slack app hands every mention it would give its agent to ``accept_slack_mention``, inside the
Slack webhook. ``read_slack_command`` takes it only when it reads exactly as a command and its
organization is in the rollout. Everything else stays with the agent, so turning the rollout off
gives people the agent back. The rollout and the projects a command may reach are decided there,
once, and the task trusts them. The run happens in this product's task, and the answer goes out
through the Slack integration the mention came in on.

The message names its subject by URL. For a pull request, the GitHub App installation on the
repository owner tells which projects may act on it. A Slack command needs no GitHub permission
check: it runs as a PostHog account that is a member of the project, the same as the review
trigger in the PostHog API and MCP. It reaches only projects of organizations that connected this
Slack workspace, the same scope the agent has.
"""

from collections.abc import Collection

import structlog

from posthog.dataclasses import frozen
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user import User
from posthog.slack.channels import post_message
from posthog.slack.markdown import slack_markdown_block

from ...facade.contracts import SlackMention
from ...logic.admission import claim, rolled_out_team_ids, within_rate_limit
from ...logic.commands import Answer, CommandRequest, DispatchOutcome, PullRequestRef, SubjectRef
from ...logic.dispatcher import Admission, CommandDispatcher
from ...logic.github import CommandGitHub
from ...logic.registry import COMMANDS
from ...logic.schema import ArgumentError, resolve_verb
from ...logic.subjects import open_subject
from .parsing import SubjectUrl, parse_slack_command

logger = structlog.get_logger(__name__)

ROLLOUT_FLAG = "slack-commands"


@frozen
class SlackCommandRequest:
    """Everything the task needs: the command, where it may run, and the thread it answers in."""

    subject: SubjectRef
    # The subject's projects in the rollout and in the organizations that connected the Slack
    # workspace, in the subject's order.
    team_ids: tuple[int, ...]
    verb: str
    argument: str
    slack_team_id: str
    slack_user_id: str
    channel: str
    thread_ts: str
    message_ts: str
    integration_id: int
    integration_team_id: int
    user_ids: tuple[int, ...]


def _installation_id(owner: str, organization_ids: Collection[str]) -> str | None:
    """The PostHog GitHub App installation on the repository owner, in one of these organizations."""
    # nosemgrep: github-installation-first-team -- only the installation id is read; the newest row wins over one left from an earlier install
    integration = (
        Integration.objects.filter(
            kind="github", config__account__name__iexact=owner, team__organization_id__in=organization_ids
        )
        .order_by("-id")
        .only("integration_id")
        .first()
    )
    return integration.integration_id if integration is not None else None


def _subject_ref(url: SubjectUrl, organization_ids: Collection[str]) -> SubjectRef | None:
    """Where the subject lives for PostHog, or None when no connected organization reaches it."""
    installation_id = _installation_id(url.repository.split("/", 1)[0], organization_ids)
    if installation_id is None:
        return None
    return PullRequestRef(installation_id=installation_id, repository=url.repository, number=url.number)


def read_slack_command(mention: SlackMention) -> SlackCommandRequest | None:
    """The command a Slack mention runs, or None to leave the mention to the agent."""
    parsed = parse_slack_command(mention.text)
    if parsed is None:
        return None
    # Only a message that reads exactly as a command skips the agent. "can you review this deeply"
    # and a mistyped option are requests the agent can still answer.
    verb = resolve_verb(parsed.verb)
    spec = COMMANDS.get(verb) if verb is not None else None
    if spec is None or isinstance(spec.parse(parsed.argument), ArgumentError):
        return None
    subject = _subject_ref(parsed.subject, mention.organization_ids)
    if subject is None:
        return None
    team_ids = rolled_out_team_ids(ROLLOUT_FLAG, subject, mention.organization_ids, only_evaluate_locally=True)
    if not team_ids:
        return None
    return SlackCommandRequest(
        subject=subject,
        team_ids=team_ids,
        verb=parsed.verb,
        argument=parsed.argument,
        slack_team_id=mention.slack_team_id,
        slack_user_id=mention.slack_user_id,
        channel=mention.channel,
        thread_ts=mention.thread_ts,
        message_ts=mention.message_ts,
        integration_id=mention.integration_id,
        integration_team_id=mention.integration_team_id,
        user_ids=mention.user_ids,
    )


class SlackMentionChannel:
    name = "slack"
    unlinked_message = (
        "Your Slack account is not linked to a PostHog account, so I can't tell who to run this as. "
        "Connect Slack in your PostHog personal settings, then try again."
    )

    def __init__(self, command: SlackCommandRequest, github: CommandGitHub | None = None) -> None:
        self._command = command
        self._github = github
        self.request = CommandRequest(
            subject=command.subject,
            verb=command.verb,
            argument=command.argument,
            ambiguous=False,
            # A Slack user has no GitHub login, and a display name is text they choose.
            requester="The requester",
            requested_via="Slack",
        )

    def admit(self) -> Admission | Answer | DispatchOutcome:
        # The message already skipped the agent, so a refusal that stays silent on GitHub answers
        # here. A duplicate stays silent: the first run answers.
        command = self._command
        claim_refusal = claim(f"commands:slack_message:{command.slack_team_id}:{command.channel}:{command.message_ts}")
        if claim_refusal == "claim_unavailable":
            return Answer(outcome=claim_refusal, message="I couldn't start this command. Try again in a few minutes.")
        if claim_refusal is not None:
            return claim_refusal
        if not within_rate_limit(f"commands:slack_user:{command.slack_team_id}:{command.slack_user_id}"):
            return Answer(
                outcome="rate_limited",
                message="You've sent a lot of commands in a short time. Try again in a few minutes.",
            )
        subject = open_subject(command.subject, command.team_ids, github=self._github)
        if isinstance(subject, Answer):
            return subject
        return Admission(team_ids=command.team_ids, subject=subject)

    def linked_users(self) -> list[User]:
        user_ids = self._command.user_ids
        users = User.objects.in_bulk(user_ids)
        return [users[user_id] for user_id in user_ids if user_id in users and users[user_id].is_active]

    def reply(self, message: str) -> None:
        command = self._command
        integration = Integration.objects.filter(
            id=command.integration_id, team_id=command.integration_team_id, kind="slack"
        ).first()
        if integration is None:
            logger.warning("slack_command_reply_integration_missing", integration_id=command.integration_id)
            return
        try:
            post_message(
                SlackIntegration(integration),
                command.channel,
                [slack_markdown_block(message)],
                message,
                thread_ts=command.thread_ts,
            )
        except Exception:
            # Best effort, as for pull request comments: a lost answer must not turn a run that
            # started into a failure.
            logger.warning("slack_command_reply_failed", exc_info=True)


def dispatch_slack_command(command: SlackCommandRequest, *, github: CommandGitHub | None = None) -> DispatchOutcome:
    return CommandDispatcher(SlackMentionChannel(command, github)).dispatch()
