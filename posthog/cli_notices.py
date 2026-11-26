"""The notices hog shows after a command, such as a version reaching its end of support.

CLI_NOTICES is the only list of them. The PostHog API sends the ones for a hog's version in a header
of every answer, and `hogli build:projections` writes the list to `hog/release/notices.generated.json`,
which every hog release copies into its manifest. "Notices" in `hog/README.md` says what each field does
and what people see.

The projection loads this file by path, without Django, so it imports only the standard library at runtime.
"""

from __future__ import annotations

import re
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

CLI_NOTICE_HEADER = "X-PostHog-CLI-Notice"

_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?$"
)
_HOG_USER_AGENT = re.compile(r"^hog/(\S+)")
_NOTICE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# hog prints the link as written, so it takes only printable ASCII with no space or `@`, as hog checks.
_NOTICE_URL = re.compile(r"^https://[!-?A-~]{1,200}$")
# The GitHub Actions runner reads it anywhere in a line as a workflow command.
_WORKFLOW_COMMAND = "##["
# hog skips a longer message, so a longer one here would never show.
MAX_MESSAGE_LENGTH = 300


# The standard library's dataclass with the flags of posthog.dataclasses.frozen, which imports Django.
@dataclass(frozen=True, kw_only=True, slots=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...]

    @staticmethod
    def parse(text: str) -> SemVer | None:
        match = _SEMVER.match(text)
        if not match:
            return None
        return SemVer(
            major=int(match[1]),
            minor=int(match[2]),
            patch=int(match[3]),
            prerelease=tuple(match[4].split(".")) if match[4] else (),
        )

    def _sort_key(self) -> tuple:
        # A release sorts above its prereleases, and numeric identifiers sort below text ones, as semver orders them.
        prerelease = tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in self.prerelease)
        return (self.major, self.minor, self.patch, not self.prerelease, prerelease)

    def __lt__(self, other: SemVer) -> bool:
        return self._sort_key() < other._sort_key()

    def __ge__(self, other: SemVer) -> bool:
        return not self < other


@dataclass(frozen=True, kw_only=True, slots=True)
class CliNotice:
    id: str
    level: Literal["info", "warning"]
    message: str
    url: str | None = None
    # The hog versions the notice is for: `from_version` and up, and below `below`.
    from_version: str | None = None
    below: str | None = None
    until: datetime | None = None
    # Only for these install kinds, such as ("homebrew", "npm-global"). hog's INSTALL_KINDS lists them.
    installs: tuple[str, ...] | None = None
    upgrade: bool = False

    # hog drops a notice it can't read, so a notice that breaks these rules fails at import, in CI, instead.
    def __post_init__(self) -> None:
        if not _NOTICE_ID.match(self.id):
            raise ValueError(f"CLI notice id {self.id!r} must be lowercase letters, digits and dashes")
        if not self.message.strip() or len(self.message) > MAX_MESSAGE_LENGTH or not self.message.isprintable():
            raise ValueError(f"CLI notice {self.id} needs a printable message of up to {MAX_MESSAGE_LENGTH} characters")
        if _WORKFLOW_COMMAND in self.message or (self.url is not None and _WORKFLOW_COMMAND in self.url):
            raise ValueError(f"CLI notice {self.id} can't hold {_WORKFLOW_COMMAND}, which GitHub Actions runs")
        if self.url is not None:
            parts = urlsplit(self.url)
            if not _NOTICE_URL.match(self.url) or not (
                parts.hostname == "posthog.com" or str(parts.hostname).endswith(".posthog.com")
            ):
                raise ValueError(f"CLI notice {self.id} can only link to an https page on posthog.com")
        for version in (self.from_version, self.below):
            if version is not None and SemVer.parse(version) is None:
                raise ValueError(f"CLI notice {self.id} names {version!r}, which isn't a semver version")
        if self.until is not None and self.until.tzinfo is None:
            raise ValueError(f"CLI notice {self.id} needs a timezone on until")

    def applies_to(self, version: SemVer, now: datetime) -> bool:
        if self.until is not None and now >= self.until:
            return False
        from_version = SemVer.parse(self.from_version) if self.from_version else None
        below = SemVer.parse(self.below) if self.below else None
        return (from_version is None or version >= from_version) and (below is None or version < below)

    # The fields hog reads, in both the header and the generated file.
    def as_item(self) -> dict[str, object]:
        item: dict[str, object] = {"id": self.id, "level": self.level, "message": self.message}
        if self.url is not None:
            item["url"] = self.url
        if self.from_version is not None:
            item["from"] = self.from_version
        if self.below is not None:
            item["below"] = self.below
        if self.until is not None:
            item["until"] = self.until.isoformat()
        if self.installs is not None:
            item["installs"] = list(self.installs)
        if self.upgrade:
            item["upgrade"] = True
        return item


# After a change, run `hogli build:projections` to regenerate hog/release/notices.generated.json.
CLI_NOTICES: tuple[CliNotice, ...] = ()


def hog_version(user_agent: str | None) -> SemVer | None:
    match = _HOG_USER_AGENT.match(user_agent or "")
    return SemVer.parse(match[1]) if match else None


def notices_for(version: SemVer, notices: Sequence[CliNotice], now: datetime) -> list[CliNotice]:
    return [notice for notice in notices if notice.applies_to(version, now)]


def header_value(notices: Sequence[CliNotice]) -> str:
    # ensure_ascii, because a header value carries only ASCII.
    return json.dumps([notice.as_item() for notice in notices], ensure_ascii=True, separators=(",", ":"))


class CliNoticeMiddleware:
    """Adds the notices in CLI_NOTICES to responses for the hog versions they name."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if not CLI_NOTICES:
            return response
        version = hog_version(request.headers.get("User-Agent"))
        if version is None:
            return response
        notices = notices_for(version, CLI_NOTICES, datetime.now(UTC))
        if notices:
            response[CLI_NOTICE_HEADER] = header_value(notices)
        return response
