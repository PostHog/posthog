"""What a command acts on: the projects it may run in, and the checks before its handler runs.

A channel names the subject with a reference from ``commands.py``. A comment names the pull request
it sits on, and a Slack message names one by its URL. Dispatch then works with the subject only
through the functions here and the ``Subject`` protocol, so it never assumes a pull request.

To add a kind of subject: add its reference and facts types to ``commands.py``, a class here that
follows ``Subject``, a case in each function below, and the kind to the commands that accept it.
"""

from typing import Any, Protocol

from posthog.models.integration import Integration

from .commands import Answer, PullRequestFacts, PullRequestRef, SubjectFacts, SubjectRef
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


def candidate_team_ids(ref: SubjectRef) -> tuple[int, ...]:
    """The projects a command on the subject may run in, before the rollout, oldest first.

    For a pull request: the projects whose GitHub integration uses the installation.
    """
    return tuple(
        dict.fromkeys(
            Integration.objects.filter(kind="github", integration_id=ref.installation_id)
            .order_by("id")
            .values_list("team_id", flat=True)
        )
    )


def rollout_key(ref: SubjectRef) -> str:
    """The flag's distinct id for the subject. The rollout targets organizations, not people."""
    return f"installation-{ref.installation_id}"


def open_subject(ref: SubjectRef, team_ids: tuple[int, ...], github: CommandGitHub | None = None) -> Subject | Answer:
    """The subject, ready to read, or the answer when PostHog cannot reach it.

    ``github`` is a client the channel already holds. Without one, the subject makes its own
    through a row of one of ``team_ids``.
    """
    github = github or InstallationGitHub.for_installation(ref.installation_id, team_ids)
    if github is None:
        return Answer(
            outcome="no_installation",
            message="I couldn't reach GitHub for this repository. Try again in a few minutes.",
        )
    return PullRequestSubject(ref, github)


def subject_payload(ref: SubjectRef) -> dict[str, str | int]:
    """The reference as a task argument. ``subject_from_payload`` reads it back."""
    return {
        "kind": ref.kind,
        "installation_id": ref.installation_id,
        "repository": ref.repository,
        "number": ref.number,
    }


def subject_from_payload(payload: dict[str, str | int]) -> SubjectRef:
    kind = payload["kind"]
    if kind == "pull_request":
        return PullRequestRef(
            installation_id=str(payload["installation_id"]),
            repository=str(payload["repository"]),
            number=int(payload["number"]),
        )
    raise ValueError(f"Unknown subject kind {kind!r}")
