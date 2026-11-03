"""What a command acts on: the projects it may run in, and the checks before its handler runs.

A channel names the subject with a reference from ``commands.py``. A comment names the pull request
it sits on, and a Slack message names a pull request or an error tracking issue by its URL. Dispatch then works with the subject only
through the functions here and the ``Subject`` protocol, so it never assumes a pull request.

To add a kind of subject: add its reference and facts types to ``commands.py``, a class here that
follows ``Subject``, a case in each function below, and the kind to the commands that accept it.
"""

from typing import Any, Protocol, assert_never

from posthog.integrations import IntegrationManager
from posthog.utils import absolute_uri

from products.error_tracking.backend.facade import api as error_tracking

from .commands import (
    Answer,
    ErrorTrackingIssueFacts,
    ErrorTrackingIssueRef,
    PullRequestFacts,
    PullRequestRef,
    SubjectFacts,
    SubjectRef,
)
from .github import CommandGitHub, GitHubCallFailed, InstallationGitHub, UnsupportedPullRequest
from .schema import CommandDeclaration


class Subject(Protocol):
    # The answer when none of the requester's accounts is a member of the subject's projects.
    not_member_message: str

    def facts(self, declaration: CommandDeclaration[Any]) -> SubjectFacts | Answer:
        """What the handler gets about the subject, or why this command must not run on it."""
        ...


class PullRequestSubject:
    not_member_message = "You aren't a member of a PostHog project that uses pull request commands on this repository."

    def __init__(self, ref: PullRequestRef, github: CommandGitHub) -> None:
        self._ref = ref
        self._github = github

    def facts(self, declaration: CommandDeclaration[Any]) -> PullRequestFacts | Answer:
        """The pull request as GitHub reports it now, or why the command must not run on it."""
        try:
            pull_request = self._github.pull_request(self._ref.repository, self._ref.number)
        except GitHubCallFailed:
            pull_request = None
        except UnsupportedPullRequest:
            return Answer(
                outcome="pull_request_unsupported",
                message="I only run commands on pull requests whose branch name uses letters, digits, `.`, `_`, `/` and `-`.",
            )
        if pull_request is None:
            return Answer(
                outcome="pull_request_unavailable",
                message="I couldn't read this pull request from GitHub. Try again in a few minutes.",
            )
        if pull_request.state != "open":
            return Answer(
                outcome="pull_request_closed", message="This pull request isn't open, so I won't run commands on it."
            )
        if pull_request.is_fork and not declaration.allows_forks:
            return Answer(
                outcome="fork_refused", message=f"`{declaration.verb}` doesn't run on pull requests from forks."
            )
        return pull_request


class ErrorTrackingIssueSubject:
    not_member_message = "You aren't a member of the PostHog project this issue belongs to."

    def __init__(self, ref: ErrorTrackingIssueRef) -> None:
        self._ref = ref

    def facts(self, declaration: CommandDeclaration[Any]) -> ErrorTrackingIssueFacts | Answer:
        not_found = Answer(outcome="issue_not_found", message="I couldn't find this issue in error tracking.")
        issue_id = self._ref.issue_id
        if not issue_id:
            owner = error_tracking.get_issue_id_for_fingerprint(self._ref.team_id, self._ref.fingerprint)
            if owner is None:
                return not_found
            issue_id = str(owner)
        issue = error_tracking.get_issue_basics(self._ref.team_id, issue_id)
        if issue is None:
            return not_found
        return ErrorTrackingIssueFacts(
            team_id=self._ref.team_id,
            issue_id=issue_id,
            status=str(issue.status),
            url=absolute_uri(f"/project/{self._ref.team_id}/error_tracking/{issue_id}"),
        )


def candidate_team_ids(ref: SubjectRef) -> tuple[int, ...]:
    """The projects a command on the subject may run in, before the rollout, oldest first.

    For a pull request: the projects whose GitHub integration uses the installation. For an error
    tracking issue: the project in its URL.
    """
    match ref:
        case PullRequestRef():
            rows = IntegrationManager.github.oauth.list_by_external_id(ref.installation_id)
            return tuple(dict.fromkeys(row.team_id for row in sorted(rows, key=lambda row: row.id)))
        case ErrorTrackingIssueRef():
            return (ref.team_id,)
        case _:
            assert_never(ref)


def rollout_key(ref: SubjectRef) -> str:
    """The flag's distinct id for the subject. The rollout targets organizations, not people."""
    match ref:
        case PullRequestRef():
            return f"installation-{ref.installation_id}"
        case ErrorTrackingIssueRef():
            return f"team-{ref.team_id}"
        case _:
            assert_never(ref)


def open_subject(ref: SubjectRef, team_ids: tuple[int, ...], github: CommandGitHub | None = None) -> Subject | Answer:
    """The subject, ready to read, or the answer when PostHog cannot reach it.

    ``github`` is a client the channel already holds. Without one, a pull request makes its own
    through a row of one of ``team_ids``.
    """
    match ref:
        case PullRequestRef():
            github = github or InstallationGitHub.for_installation(ref.installation_id, team_ids)
            if github is None:
                return Answer(
                    outcome="no_installation",
                    message="I couldn't reach GitHub for this repository. Try again in a few minutes.",
                )
            return PullRequestSubject(ref, github)
        case ErrorTrackingIssueRef():
            return ErrorTrackingIssueSubject(ref)
        case _:
            assert_never(ref)


def subject_payload(ref: SubjectRef) -> dict[str, str | int]:
    """The reference as a task argument. ``subject_from_payload`` reads it back."""
    match ref:
        case PullRequestRef():
            return {
                "kind": ref.kind,
                "installation_id": ref.installation_id,
                "repository": ref.repository,
                "number": ref.number,
            }
        case ErrorTrackingIssueRef():
            return {"kind": ref.kind, "team_id": ref.team_id, "issue_id": ref.issue_id, "fingerprint": ref.fingerprint}
        case _:
            assert_never(ref)


def subject_from_payload(payload: dict[str, str | int]) -> SubjectRef:
    kind = payload["kind"]
    if kind == "pull_request":
        return PullRequestRef(
            installation_id=str(payload["installation_id"]),
            repository=str(payload["repository"]),
            number=int(payload["number"]),
        )
    if kind == "error_tracking_issue":
        return ErrorTrackingIssueRef(
            team_id=int(payload["team_id"]),
            issue_id=str(payload["issue_id"]),
            fingerprint=str(payload.get("fingerprint", "")),
        )
    raise ValueError(f"Unknown subject kind {kind!r}")
