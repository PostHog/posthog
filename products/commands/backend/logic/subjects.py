"""What a command acts on. Pull requests are the only kind so far.

A channel names the subject: a comment names the pull request it sits on, and a message can name one
by its URL. The subject decides which projects a command may run in, and reads the facts its handler
gets. Another kind of subject, such as a PostHog dashboard, adds a reference type and a class here.
"""

from typing import Any

from posthog.models.integration import Integration

from .commands import Answer, PullRequestFacts, PullRequestRef
from .github import CommandGitHub, GitHubCallFailed, UnsupportedPullRequest
from .schema import CommandDeclaration


class PullRequestSubject:
    def __init__(self, ref: PullRequestRef, github: CommandGitHub) -> None:
        self.ref = ref
        self._github = github

    def candidate_team_ids(self) -> list[int]:
        """Projects whose GitHub integration uses the pull request's installation, oldest first."""
        return list(
            dict.fromkeys(
                Integration.objects.filter(kind="github", integration_id=self.ref.installation_id)
                .order_by("id")
                .values_list("team_id", flat=True)
            )
        )

    def facts(self, declaration: CommandDeclaration[Any]) -> PullRequestFacts | Answer:
        """The pull request as GitHub reports it now, or why the command must not run on it."""
        try:
            pull_request = self._github.pull_request(self.ref.repository, self.ref.number)
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
