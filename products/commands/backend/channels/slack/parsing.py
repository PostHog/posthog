"""Reads one command out of a Slack message that mentions the PostHog app.

The Slack app removes its own mention and hands over plain text. What is left must be the command
and the URL of its subject, in either order. For a pull request: ``review --deep https://github.com/PostHog/posthog/pull/123``
as in a shell, or ``https://github.com/PostHog/posthog/pull/123 review --deep``. Options and free
text, such as the focus of ``qa``, may also follow the URL. With the verb first, every word before
the URL must be an option, so a valued option takes the ``--name=value`` form there. Anything else is
not a command and stays with the agent, so this parser is strict on purpose: a sentence that happens
to hold a URL, such as "review this <URL>", never runs a command.

A new kind of subject adds its URL type and a pattern in ``_read_subject_url``.
"""

import re

from posthog.dataclasses import frozen

from ...logic.commands import REPOSITORY_NAME_RE
from ...logic.schema import sanitize_argument

_PULL_REQUEST_URL_RE = re.compile(
    r"https://github\.com/(?P<repository>[^/\s]+/[^/\s]+)/pull/(?P<number>[0-9]{1,9})(?:[/#?]\S*)?"
)
_VERB_RE = re.compile(r"[A-Za-z][\w-]{0,31}")
# The grammar reads an en or em dash as `--`, because macOS autocorrect types one.
_OPTION_PREFIXES = ("-", "–", "—")


@frozen
class PullRequestUrl:
    repository: str
    number: int


SubjectUrl = PullRequestUrl


@frozen
class SlackCommand:
    subject: SubjectUrl
    verb: str
    argument: str


def may_hold_command(text: str) -> bool:
    """False when the message names nothing a command acts on. No queries, any message format."""
    return _PULL_REQUEST_URL_RE.search(text) is not None


def _read_subject_url(word: str) -> SubjectUrl | None:
    match = _PULL_REQUEST_URL_RE.fullmatch(word)
    if match is None:
        return None
    repository = match.group("repository")
    number = int(match.group("number"))
    if not REPOSITORY_NAME_RE.fullmatch(repository) or number < 1:
        return None
    return PullRequestUrl(repository=repository, number=number)


def parse_slack_command(text: str) -> SlackCommand | None:
    words = text.split()
    if len(words) < 2:
        return None
    first_url = _read_subject_url(words[0])
    if first_url is not None:
        subject, verb, argument_words = first_url, words[1], words[2:]
    else:
        verb = words[0]
        url_index = next(
            (index for index, word in enumerate(words[1:], start=1) if not word.startswith(_OPTION_PREFIXES)), None
        )
        if url_index is None:
            return None
        url = _read_subject_url(words[url_index])
        if url is None:
            return None
        subject = url
        argument_words = [*words[1:url_index], *words[url_index + 1 :]]
    if not _VERB_RE.fullmatch(verb):
        return None
    return SlackCommand(subject=subject, verb=verb.lower(), argument=sanitize_argument(" ".join(argument_words)))
