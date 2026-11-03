"""The command contract: what a channel delivers, what a handler receives and what it answers.

A handler is the only place that knows the product it dispatches into. Everything that decides
whether a command may run at all lives in ``dispatcher.py`` and the channel, and runs before any
handler, so a new command inherits the full set of checks by being declared in ``schema.py``.
"""

import re
from typing import ClassVar, Literal

from posthog.dataclasses import frozen

# The name goes into GitHub API paths, so it must be exactly `owner/name`.
REPOSITORY_NAME_RE = re.compile(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}")

SubjectKind = Literal["pull_request", "error_tracking_issue"]
SUBJECT_NAMES: dict[SubjectKind, str] = {
    "pull_request": "pull requests",
    "error_tracking_issue": "error tracking issues",
}

DispatchOutcome = Literal[
    "duplicate",
    "claim_unavailable",
    "not_rolled_out",
    "no_installation",
    "no_write_access",
    "permission_lookup_failed",
    "rate_limited",
    "ambiguous",
    "help",
    "unknown_command",
    "invalid_arguments",
    "wrong_subject",
    "unlinked",
    "account_refused",
    "no_project",
    "pull_request_unavailable",
    "pull_request_unsupported",
    "pull_request_closed",
    "issue_not_found",
    "fork_refused",
    "access_denied",
    "accepted",
    "refused",
    "failed",
]


@frozen
class Answer:
    """Dispatch stops here and tells the requester why."""

    outcome: DispatchOutcome
    message: str


@frozen
class PullRequestRef:
    """A pull request as a channel names it, before anything about it is checked."""

    kind: ClassVar[SubjectKind] = "pull_request"

    installation_id: str
    repository: str
    number: int

    def describe(self) -> str:
        return f"{self.repository}#{self.number}"


@frozen
class ErrorTrackingIssueRef:
    """An error tracking issue as a PostHog URL names it, before anything about it is checked.

    The URL names the issue by id, or by a fingerprint that follows the issue through merges, as the
    links in error tracking's Slack alerts do. Exactly one of the two is set.
    """

    kind: ClassVar[SubjectKind] = "error_tracking_issue"

    team_id: int
    issue_id: str = ""
    fingerprint: str = ""

    def describe(self) -> str:
        return f"error tracking issue {self.issue_id}" if self.issue_id else "error tracking issue by fingerprint"


SubjectRef = PullRequestRef | ErrorTrackingIssueRef


@frozen
class CommandTarget:
    """The projects a command's product acts in, out of the candidates dispatch offered it."""

    team_ids: tuple[int, ...]
    # The answer when none of the requester's accounts is a member of these projects.
    not_member_message: str


@frozen
class CommandRequest:
    """A command as a channel delivers it: what it acts on, what was asked, and who asked.

    It holds identifiers and the requester's own command text only, never text other people wrote.
    """

    subject: SubjectRef
    verb: str
    argument: str
    ambiguous: bool
    # How a prompt names the person who asked, such as `@octo`. Never used to identify them.
    requester: str
    # Where they asked, to finish "asked for this run from ...", such as "a pull request comment".
    requested_via: str


@frozen
class PullRequestFacts:
    """What GitHub reported about the pull request when the task read it.

    Read from the API rather than the webhook payload, so the head commit is the one that existed
    after the commenter's permission was confirmed. Free text such as the title and body is not
    kept: nothing here can carry an instruction.
    """

    repository: str
    number: int
    url: str
    state: str
    draft: bool
    head_sha: str
    head_branch: str
    is_fork: bool


@frozen
class ErrorTrackingIssueFacts:
    """The issue as error tracking reports it when the task read it.

    The issue's name is not kept: it comes from captured exception text, which people outside the
    organization can write, so no reply may repeat it.
    """

    team_id: int
    issue_id: str
    status: str
    url: str


SubjectFacts = PullRequestFacts | ErrorTrackingIssueFacts


# Where a channel wants the result of work that finishes after the command answered. Only the
# channel reads it, so the core keeps it as plain data.
FollowUpAddress = dict[str, str | int]


@frozen
class ProjectMember:
    """A project the commenter may act in, and the commenter's PostHog account that acts there.

    One GitHub account can be linked to several PostHog accounts, for example a work and a personal
    one, so the account goes with the project the command picks.
    """

    team_id: int
    user_id: int


@frozen
class CommandContext:
    request: CommandRequest
    subject: SubjectFacts
    # Best candidate first. Every entry passed the membership, rollout and resource-access checks
    # for this command. A project appears once per linked account that is a member of it.
    members: tuple[ProjectMember, ...]
    follow_up: FollowUpAddress | None = None

    @property
    def pull_request(self) -> PullRequestFacts:
        """The subject of a command that accepts only pull requests."""
        if not isinstance(self.subject, PullRequestFacts):
            raise TypeError(f"Expected a pull request, got {type(self.subject).__name__}")
        return self.subject

    @property
    def issue(self) -> ErrorTrackingIssueFacts:
        """The subject of a command that accepts only error tracking issues."""
        if not isinstance(self.subject, ErrorTrackingIssueFacts):
            raise TypeError(f"Expected an error tracking issue, got {type(self.subject).__name__}")
        return self.subject


@frozen
class CommandOutcome:
    accepted: bool
    # Markdown posted back where the command came from. Handlers build it from fixed text and values
    # PostHog or GitHub produced, never from the request, so a reply cannot be made to say
    # something the requester wrote.
    message: str
