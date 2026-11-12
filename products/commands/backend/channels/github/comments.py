"""Commands from pull request comments: who may ask, and how the answer goes back.

A comment passes these silent checks, in this order, before the shared steps in
``logic/dispatcher.py``:

1. A project on this installation is in the rollout. Until one is, nothing below runs and the bot
   says nothing.
2. The comment is new to us. Ingress dedups the delivery, and this claims the comment itself, so
   a redelivery or a second consumer path cannot run one comment twice.
3. The commenter is within their rate limit. This runs before any GitHub call, so a flood of
   comments costs no GitHub quota.
4. GitHub says the commenter's account, matched by its numeric id, can write to the repository.
   The webhook's `author_association` only filtered noise; organization members can lack write
   access to a given repository.

The commenter's PostHog accounts come from ``posthog.github.requesters``, which matches them on
GitHub's numeric user id.
"""

import structlog

from posthog.github.requesters import GITHUB_WRITE_PERMISSIONS, users_linked_to_github_account
from posthog.models.user import User

from ...logic.admission import claim, release, rolled_out_team_ids, within_rate_limit
from ...logic.commands import Answer, CommandRequest, DispatchOutcome, FollowUpAddress, PullRequestRef
from ...logic.dispatcher import Admission, CommandDispatcher
from ...logic.github import CommandGitHub, GitHubCallFailed, InstallationGitHub, Reaction
from ...logic.subjects import open_subject
from .intake import CommentCommandRequest

logger = structlog.get_logger(__name__)

ROLLOUT_FLAG = "github-commands"


def _claim_key(comment_id: int) -> str:
    return f"commands:github_comment:{comment_id}"


class GitHubCommentChannel:
    name = "github"
    # The work posts its result on the pull request the comment sits on.
    follow_up: FollowUpAddress | None = None
    unlinked_message = (
        "Your GitHub account is not linked to a PostHog account, so I can't tell who to run this as. "
        "Connect GitHub in your PostHog personal settings, then comment again."
    )

    def __init__(self, comment: CommentCommandRequest, github: CommandGitHub | None = None) -> None:
        self._comment = comment
        self._github = github
        self.request = CommandRequest(
            subject=PullRequestRef(
                installation_id=comment.installation_id, repository=comment.repository, number=comment.pr_number
            ),
            verb=comment.verb,
            argument=comment.argument,
            ambiguous=comment.ambiguous,
            requester=f"@{comment.commenter_login}",
            requested_via="a pull request comment",
        )

    def admit(self) -> Admission | DispatchOutcome:
        comment = self._comment
        # Before any GitHub call: the App is installed on repositories of organizations that never
        # turned commands on, and the bot must stay silent there.
        team_ids = rolled_out_team_ids(ROLLOUT_FLAG, self.request.subject)
        if not team_ids:
            return "not_rolled_out"
        claim_refusal = claim(_claim_key(comment.comment_id))
        if claim_refusal is not None:
            return claim_refusal
        if not within_rate_limit(f"commands:github_commenter:{comment.commenter_github_id}"):
            return "rate_limited"
        if self._github is None:
            self._github = InstallationGitHub.for_installation(comment.installation_id, team_ids)
            if self._github is None:
                return "no_installation"
        try:
            permission = self._github.collaborator_permission(
                comment.repository, comment.commenter_login, comment.commenter_github_id
            )
        except GitHubCallFailed:
            logger.warning("github_command_permission_lookup_failed", repository=comment.repository, exc_info=True)
            # Nothing ran, so a redelivery may try again.
            release(_claim_key(comment.comment_id))
            return "permission_lookup_failed"
        if permission not in GITHUB_WRITE_PERMISSIONS:
            return "no_write_access"
        self._react("eyes")
        subject = open_subject(self.request.subject, team_ids, github=self._github)
        if isinstance(subject, Answer):
            return subject.outcome
        return Admission(team_ids=team_ids, subject=subject)

    def linked_users(self) -> list[User]:
        return users_linked_to_github_account(self._comment.commenter_github_id)

    def reply(self, message: str) -> None:
        comment = self._comment
        if self._github is None:
            return
        # The marker lets a reader find the comment a reply answers. The login is GitHub's, not text
        # from the comment, so the mention pings only the person who asked.
        body = f"<!-- posthog-github-command:{comment.comment_id} -->\n@{comment.commenter_login} {message}"
        self._github.reply(comment.repository, comment.pr_number, body)

    def dispatch(self) -> DispatchOutcome:
        outcome = CommandDispatcher(self).dispatch()
        if outcome == "accepted":
            self._react("rocket")
        return outcome

    def _react(self, reaction: Reaction) -> None:
        if self._github is not None:
            self._github.react(self._comment.repository, self._comment.comment_id, reaction)


def dispatch_comment_command(comment: CommentCommandRequest, *, github: CommandGitHub | None = None) -> DispatchOutcome:
    return GitHubCommentChannel(comment, github).dispatch()
