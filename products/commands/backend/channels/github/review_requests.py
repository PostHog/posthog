"""Reviews requested by asking the ``posthog-review`` team to review a pull request.

The request runs ``review`` through the same checks as a comment command (see ``comments.py``),
with the person who asked as the requester. Once the request reaches GitHub, the team's review
request is removed, so asking the team again asks for another review. GitHub shows the re-request
button only next to reviewers who submitted a review, and a team never does.
"""

import structlog

from posthog.models.user import User

from ...logic.admission import claim, release, rolled_out_team_ids, within_rate_limit
from ...logic.commands import Answer, CommandRequest, DispatchOutcome, FollowUpAddress, PullRequestRef
from ...logic.dispatcher import Admission, CommandDispatcher
from ...logic.github import CommandGitHub, GitHubCallFailed, InstallationGitHub
from ...logic.subjects import open_subject
from .comments import ROLLOUT_FLAG, WRITE_PERMISSIONS, users_linked_to_github_account
from .intake import REVIEW_TEAM_SLUG, ReviewTeamRequest

logger = structlog.get_logger(__name__)


def _claim_key(delivery_id: str) -> str:
    return f"commands:github_review_request:{delivery_id}"


class GitHubReviewRequestChannel:
    name = "github_review_request"
    follow_up: FollowUpAddress | None = None
    unlinked_message = (
        "Your GitHub account is not linked to a PostHog account, so I can't tell who to run this review as. "
        "Connect GitHub in your PostHog personal settings, then request the review again."
    )

    def __init__(self, review_request: ReviewTeamRequest, github: CommandGitHub | None = None) -> None:
        self._review_request = review_request
        self._github = github
        self.request = CommandRequest(
            subject=PullRequestRef(
                installation_id=review_request.installation_id,
                repository=review_request.repository,
                number=review_request.pr_number,
            ),
            verb="review",
            argument="",
            ambiguous=False,
            requester=f"@{review_request.requester_login}",
            requested_via=f"a review request for the {REVIEW_TEAM_SLUG} team",
        )

    def admit(self) -> Admission | DispatchOutcome:
        review_request = self._review_request
        team_ids = rolled_out_team_ids(ROLLOUT_FLAG, self.request.subject)
        if not team_ids:
            return "not_rolled_out"
        claim_refusal = claim(_claim_key(review_request.delivery_id))
        if claim_refusal is not None:
            return claim_refusal
        # The same budget as comments, so switching triggers does not double what one person may start.
        if not within_rate_limit(f"commands:github_commenter:{review_request.requester_github_id}"):
            return "rate_limited"
        if self._github is None:
            self._github = InstallationGitHub.for_installation(review_request.installation_id, team_ids)
            if self._github is None:
                return "no_installation"
        try:
            permission = self._github.collaborator_permission(
                review_request.repository, review_request.requester_login, review_request.requester_github_id
            )
        except GitHubCallFailed:
            logger.warning(
                "github_review_request_permission_lookup_failed", repository=review_request.repository, exc_info=True
            )
            release(_claim_key(review_request.delivery_id))
            return "permission_lookup_failed"
        if permission not in WRITE_PERMISSIONS:
            return "no_write_access"
        subject = open_subject(self.request.subject, team_ids, github=self._github)
        if isinstance(subject, Answer):
            return subject.outcome
        return Admission(team_ids=team_ids, subject=subject)

    def linked_users(self) -> list[User]:
        return users_linked_to_github_account(self._review_request.requester_github_id)

    def reply(self, message: str) -> None:
        review_request = self._review_request
        if self._github is None:
            return
        body = (
            f"<!-- posthog-github-review-request:{review_request.delivery_id} -->\n"
            f"@{review_request.requester_login} {message}"
        )
        self._github.reply(review_request.repository, review_request.pr_number, body)

    def dispatch(self) -> DispatchOutcome:
        outcome = CommandDispatcher(self).dispatch()
        if self._github is not None and outcome != "permission_lookup_failed":
            self._github.remove_team_review_request(
                self._review_request.repository, self._review_request.pr_number, REVIEW_TEAM_SLUG
            )
        return outcome


def dispatch_review_team_request(
    review_request: ReviewTeamRequest, *, github: CommandGitHub | None = None
) -> DispatchOutcome:
    return GitHubReviewRequestChannel(review_request, github).dispatch()
