"""Reads one pull request command out of a Slack message that mentions the PostHog app.

The Slack app removes its own mention and hands over plain text. What is left must be a pull
request URL and a command, in that order: ``https://github.com/PostHog/posthog/pull/123 review
--deep``. Anything else is not a command and stays with the agent, so this parser is strict on
purpose: a sentence that happens to hold a pull request URL never runs a command.
"""

import re

from posthog.dataclasses import frozen

from ...logic.commands import REPOSITORY_NAME_RE
from ...logic.schema import sanitize_argument

_PULL_REQUEST_URL = r"https://github\.com/(?P<repository>[^/\s]+/[^/\s]+)/pull/(?P<number>[0-9]{1,9})"
_PULL_REQUEST_URL_RE = re.compile(_PULL_REQUEST_URL)
_COMMAND_RE = re.compile(
    rf"^\s*{_PULL_REQUEST_URL}(?:[/#?]\S*)?\s+(?P<verb>[A-Za-z][\w-]{{0,31}})(?P<rest>(?:\s.*)?)$",
    re.DOTALL,
)


@frozen
class SlackPullRequestCommand:
    repository: str
    pr_number: int
    verb: str
    argument: str


def may_hold_command(text: str) -> bool:
    """False when the message names nothing a command acts on. No queries, any message format."""
    return _PULL_REQUEST_URL_RE.search(text) is not None


def parse_slack_command(text: str) -> SlackPullRequestCommand | None:
    match = _COMMAND_RE.match(text)
    if match is None:
        return None
    repository = match.group("repository")
    pr_number = int(match.group("number"))
    if not REPOSITORY_NAME_RE.fullmatch(repository) or pr_number < 1:
        return None
    return SlackPullRequestCommand(
        repository=repository,
        pr_number=pr_number,
        verb=match.group("verb").lower(),
        argument=sanitize_argument(match.group("rest")),
    )
