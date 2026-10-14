"""What a command acts on. Pull requests are the only kind, and dispatch builds this class directly.

A channel names the pull request: a comment names the one it sits on, and a Slack message names one
by its URL. The subject reads the facts a handler gets, and refuses a pull request no command may
touch.
"""

from typing import Any

from .commands import Answer, PullRequestFacts, PullRequestRef
from .github import CommandGitHub, GitHubCallFailed, UnsupportedPullRequest
from .schema import CommandDeclaration


class PullRequestSubject:
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
