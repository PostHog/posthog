"""The command contract: what a channel delivers, what a handler receives and what it answers.

A handler is the only place that knows the product it dispatches into. Everything that decides
whether a command may run at all lives in ``dispatcher.py`` and the channel, and runs before any
handler, so a new command inherits the full set of checks by being declared in ``schema.py``.
"""

import re
from typing import Literal

from posthog.dataclasses import frozen

# The name goes into GitHub API paths, so it must be exactly `owner/name`.
REPOSITORY_NAME_RE = re.compile(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}")

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
    "unlinked",
    "account_refused",
    "no_project",
    "pull_request_unavailable",
    "pull_request_unsupported",
    "pull_request_closed",
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

    installation_id: str
    repository: str
    number: int


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

    subject: PullRequestRef
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
    pull_request: PullRequestFacts
    # Best candidate first. Every entry passed the membership, rollout and resource-access checks
    # for this command. A project appears once per linked account that is a member of it.
    members: tuple[ProjectMember, ...]


@frozen
class CommandOutcome:
    accepted: bool
    # Markdown posted back on the pull request. Handlers build it from fixed text and values
    # PostHog or GitHub produced, never from the comment, so a reply cannot be made to say
    # something the commenter wrote.
    message: str
