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

The commenter's PostHog accounts are matched on GitHub's numeric user id, never on the login. A
login can be renamed and then claimed by someone else, but the id stays with the account. Only
identities that GitHub itself confirmed to PostHog count: the GitHub account a user connected in
PostHog, or the one they log in with. A login typed into a profile or saved on a project
integration does not.
"""

from datetime import datetime

from django.core.cache import cache

import structlog
from social_django.models import UserSocialAuth

from posthog.models.integration import Integration
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.permissions import posthog_feature_flag_enabled
from posthog.token_bucket import BucketDecision, Budget, consume

from ...logic.commands import CommandRequest, DispatchOutcome, PullRequestRef
from ...logic.dispatcher import Admission, CommandDispatcher
from ...logic.github import CommandGitHub, GitHubCallFailed, InstallationGitHub, Reaction
from .intake import CommentCommandRequest

logger = structlog.get_logger(__name__)

ROLLOUT_FLAG = "github-commands"
_WRITE_PERMISSIONS = frozenset({"admin", "maintain", "write"})
_CLAIM_TTL_SECONDS = 7 * 24 * 60 * 60
# A person typing commands rarely sends more than a few in a row. The cap stops a script or a
# runaway agent with a member's account from fanning out runs that cost money.
_COMMENTER_BUDGET = Budget(burst=5, per_hour=30)


def _claim_key(comment_id: int) -> str:
    return f"commands:github_comment:{comment_id}"


def _claim_comment(comment_id: int) -> DispatchOutcome | None:
    """None when this call claimed the comment, else the outcome that stops dispatch."""
    try:
        claimed = cache.add(_claim_key(comment_id), 1, timeout=_CLAIM_TTL_SECONDS)
    except Exception:
        # Fail closed: the cache shares Redis with the Celery broker, so an outage that drops this
        # command drops it anyway, while failing open lets a redelivery start a second paid run.
        logger.warning("github_command_claim_failed", comment_id=comment_id, exc_info=True)
        return "claim_unavailable"
    return None if claimed else "duplicate"


def _release_comment(comment_id: int) -> None:
    try:
        cache.delete(_claim_key(comment_id))
    except Exception:
        logger.warning("github_command_release_failed", comment_id=comment_id, exc_info=True)


def _within_rate_limit(github_user_id: int) -> bool:
    decision = consume(f"commands:github_commenter:{github_user_id}", _COMMENTER_BUDGET)
    # Fail open when Redis can't answer, like the other per-caller buckets.
    return not isinstance(decision, BucketDecision) or decision.allowed


def _rolled_out_team_ids(installation_id: str) -> frozenset[int]:
    """Projects on this installation whose organization is in the rollout."""
    team_ids = set(
        Integration.objects.filter(kind="github", integration_id=installation_id).values_list("team_id", flat=True)
    )
    teams = Team.objects.filter(id__in=team_ids).only("id", "organization_id")
    return frozenset(
        team.id
        for team in teams
        if posthog_feature_flag_enabled(
            ROLLOUT_FLAG,
            # The rollout targets organizations, so the person behind the comment does not matter yet.
            f"github-commands-installation-{installation_id}",
            organization_id=team.organization_id,
            team_id=team.id,
        )
    )


def _linked_users(github_user_id: int) -> list[User]:
    """The active users linked to the GitHub account, most recently linked first."""
    links = [
        *UserIntegration.objects.filter(
            kind=UserIntegration.IntegrationKind.GITHUB,
            # The id arrives as a JSON number from the GitHub OAuth flow. Older rows may hold a string.
            config__github_user__id__in=[github_user_id, str(github_user_id)],
        ).values_list("user_id", "created_at"),
        *UserSocialAuth.objects.filter(provider="github", uid=str(github_user_id)).values_list("user_id", "created"),
    ]
    linked_at: dict[int, datetime] = {}
    for user_id, created_at in links:
        linked_at[user_id] = max(created_at, linked_at.get(user_id, created_at))
    users = User.objects.filter(id__in=linked_at, is_active=True)
    return sorted(users, key=lambda user: (linked_at[user.id], user.id), reverse=True)


class GitHubCommentChannel:
    name = "github"
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
        rolled_out_team_ids = _rolled_out_team_ids(comment.installation_id)
        if not rolled_out_team_ids:
            return "not_rolled_out"
        claim_refusal = _claim_comment(comment.comment_id)
        if claim_refusal is not None:
            return claim_refusal
        if not _within_rate_limit(comment.commenter_github_id):
            return "rate_limited"
        if self._github is None:
            self._github = InstallationGitHub.for_installation(comment.installation_id, rolled_out_team_ids)
            if self._github is None:
                return "no_installation"
        try:
            permission = self._github.collaborator_permission(
                comment.repository, comment.commenter_login, comment.commenter_github_id
            )
        except GitHubCallFailed:
            logger.warning("github_command_permission_lookup_failed", repository=comment.repository, exc_info=True)
            # Nothing ran, so a redelivery may try again.
            _release_comment(comment.comment_id)
            return "permission_lookup_failed"
        if permission not in _WRITE_PERMISSIONS:
            return "no_write_access"
        return Admission(github=self._github, rolled_out_team_ids=rolled_out_team_ids)

    def acknowledge(self) -> None:
        self._react("eyes")

    def linked_users(self) -> list[User]:
        return _linked_users(self._comment.commenter_github_id)

    def reply(self, message: str) -> None:
        comment = self._comment
        if self._github is None:
            return
        # The marker lets a reader find the comment a reply answers. The login is GitHub's, not text
        # from the comment, so the mention pings only the person who asked.
        body = f"<!-- posthog-github-command:{comment.comment_id} -->\n@{comment.commenter_login} {message}"
        self._github.reply(comment.repository, comment.pr_number, body)

    def mark_accepted(self) -> None:
        self._react("rocket")

    def _react(self, reaction: Reaction) -> None:
        if self._github is not None:
            self._github.react(self._comment.repository, self._comment.comment_id, reaction)


def dispatch_comment_command(comment: CommentCommandRequest, *, github: CommandGitHub | None = None) -> DispatchOutcome:
    return CommandDispatcher(GitHubCommentChannel(comment, github)).dispatch()
