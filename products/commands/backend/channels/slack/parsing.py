"""Reads one command out of a Slack message that mentions the PostHog app.

The Slack app removes its own mention and hands over plain text. What is left must be the command
and the URL of its subject, in either order: a pull request on GitHub, or an error tracking issue
in this PostHog instance. For a pull request: ``review --deep https://github.com/PostHog/posthog/pull/123``
as in a shell, or ``https://github.com/PostHog/posthog/pull/123 review --deep``. Options and free
text, such as the focus of ``qa``, may also follow the URL. With the verb first, every word before
the URL must be an option, so a valued option takes the ``--name=value`` form there. Anything else is
not a command and stays with the agent, so this parser is strict on purpose: a sentence that happens
to hold a URL, such as "review this <URL>", never runs a command.

A new kind of subject adds its URL type and a pattern in ``_read_subject_url``.
"""

import re
from urllib.parse import unquote, urlsplit

from django.conf import settings

from posthog.dataclasses import frozen

from ...logic.commands import REPOSITORY_NAME_RE
from ...logic.schema import sanitize_argument

_PULL_REQUEST_URL_RE = re.compile(
    r"https://github\.com/(?P<repository>[^/\s]+/[^/\s]+)/pull/(?P<number>[0-9]{1,9})(?:[/#?]\S*)?"
)
# The app's own URL for an issue. The origin is checked against this instance separately, because
# project ids repeat across regions.
_ERROR_TRACKING_ISSUE_URL_RE = re.compile(
    r"(?P<origin>https?://[^/\s]+)/project/(?P<team_id>[0-9]{1,12})/error[_-]tracking/"
    r"(?:(?P<issue_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"|fingerprint/(?P<fingerprint>[^/\s?#]{1,512}))(?:[/#?]\S*)?"
)
# The US app answers on both hosts.
_ORIGIN_ALIASES = {"https://us.posthog.com": "https://app.posthog.com"}
_VERB_RE = re.compile(r"[A-Za-z][\w-]{0,31}")
# The grammar reads an en or em dash as `--`, because macOS autocorrect types one.
_OPTION_PREFIXES = ("-", "–", "—")


@frozen
class PullRequestUrl:
    repository: str
    number: int


@frozen
class ErrorTrackingIssueUrl:
    team_id: int
    issue_id: str = ""
    fingerprint: str = ""


SubjectUrl = PullRequestUrl | ErrorTrackingIssueUrl


@frozen
class SlackCommand:
    subject: SubjectUrl
    verb: str
    argument: str


def may_hold_command(text: str) -> bool:
    """False when the message names nothing a command acts on. No queries, any message format."""
    return _PULL_REQUEST_URL_RE.search(text) is not None or _ERROR_TRACKING_ISSUE_URL_RE.search(text) is not None


def _instance_origins() -> set[str]:
    parts = urlsplit(settings.SITE_URL)
    origin = f"{parts.scheme}://{parts.netloc}".lower()
    return {origin, _ORIGIN_ALIASES[origin]} if origin in _ORIGIN_ALIASES else {origin}


def _read_subject_url(word: str) -> SubjectUrl | None:
    issue = _ERROR_TRACKING_ISSUE_URL_RE.fullmatch(word)
    if issue is not None:
        if issue.group("origin").lower() not in _instance_origins():
            return None
        team_id = int(issue.group("team_id"))
        if issue.group("issue_id") is not None:
            return ErrorTrackingIssueUrl(team_id=team_id, issue_id=issue.group("issue_id").lower())
        return ErrorTrackingIssueUrl(team_id=team_id, fingerprint=unquote(issue.group("fingerprint")))
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
