"""Checks on an uploaded transcript's name, size and bytes. Pure: no storage, no database."""

import re
from pathlib import PurePosixPath

from posthog.models.utils import (
    HEATMAP_SCREENSHOT_SECRET_PREFIX,
    OAUTH_ACCESS_TOKEN_PREFIX,
    OAUTH_REFRESH_TOKEN_PREFIX,
    PERSONAL_API_KEY_PREFIX,
    SECRET_API_TOKEN_PREFIX,
)

from ..facade.contracts import ALLOWED_TRANSCRIPT_EXTENSIONS, MAX_TRANSCRIPT_SIZE_BYTES, UploadRejected
from ..facade.enums import SecretKind, UploadRejectionReason

MIN_TRANSCRIPT_SIZE_BYTES = 1
MAX_DISPLAY_FILENAME_LENGTH = 255
MAX_STORED_FILENAME_LENGTH = 100
FALLBACK_FILENAME_STEM = "transcript"

CONTENT_TYPE_BY_EXTENSION: dict[str, str] = {
    ".jsonl": "application/jsonl",
    ".json": "application/json",
    ".md": "text/markdown",
    ".txt": "text/plain",
}

_UNSAFE_FILENAME_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")


def _posthog_token_pattern(*prefixes: str) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(prefix) for prefix in prefixes)
    return re.compile(rf"(?<![A-Za-z0-9_])(?:{alternatives})[A-Za-z0-9]{{20,}}")


# Credentials that must not reach our storage. Each pattern needs the token's own prefix and a
# realistic length, so prose that only mentions a prefix does not match. PostHog project tokens
# (`phc_`) are public by design and are not in this list.
SECRET_PATTERNS: tuple[tuple[SecretKind, re.Pattern[str]], ...] = (
    (SecretKind.POSTHOG_PERSONAL_API_KEY, _posthog_token_pattern(PERSONAL_API_KEY_PREFIX)),
    (
        SecretKind.POSTHOG_SECRET_KEY,
        _posthog_token_pattern(SECRET_API_TOKEN_PREFIX, HEATMAP_SCREENSHOT_SECRET_PREFIX),
    ),
    (
        SecretKind.POSTHOG_OAUTH_TOKEN,
        _posthog_token_pattern(OAUTH_ACCESS_TOKEN_PREFIX, OAUTH_REFRESH_TOKEN_PREFIX),
    ),
    # OpenAI, Anthropic and similar keys. The lookahead asks for a digit, which random keys have and
    # kebab-case names that start with `sk-` usually do not.
    (SecretKind.PROVIDER_API_KEY, re.compile(r"(?<![A-Za-z0-9_-])sk-(?=[A-Za-z0-9_-]*[0-9])[A-Za-z0-9_-]{20,}")),
    (SecretKind.AWS_ACCESS_KEY_ID, re.compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])")),
    (
        SecretKind.GITHUB_TOKEN,
        re.compile(r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,})"),
    ),
    (SecretKind.GITLAB_TOKEN, re.compile(r"(?<![A-Za-z0-9_-])glpat-[A-Za-z0-9_-]{20,}")),
    (SecretKind.GOOGLE_API_KEY, re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])")),
    (SecretKind.SLACK_TOKEN, re.compile(r"(?<![A-Za-z0-9_-])xox[a-z]-[A-Za-z0-9-]{10,}")),
    (SecretKind.PRIVATE_KEY, re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
)


def display_filename(filename: str) -> str:
    """The name to show people. Control characters go, so the name cannot break a header or a log line."""
    printable = "".join(character for character in filename if character.isprintable()).strip()
    return printable[:MAX_DISPLAY_FILENAME_LENGTH]


def file_extension(filename: str) -> str:
    return PurePosixPath(filename.replace("\\", "/")).suffix.lower()


def storage_filename(filename: str) -> str:
    """A name that is safe as the last segment of an object key and in a Content-Disposition header."""
    extension = file_extension(filename)
    stem = PurePosixPath(filename.replace("\\", "/")).stem
    safe_stem = _UNSAFE_FILENAME_CHARACTERS.sub("_", stem).strip("._") or FALLBACK_FILENAME_STEM

    return safe_stem[: MAX_STORED_FILENAME_LENGTH - len(extension)] + extension


def content_type_for(filename: str) -> str:
    return CONTENT_TYPE_BY_EXTENSION[file_extension(filename)]


def check_extension(filename: str) -> None:
    if file_extension(filename) not in ALLOWED_TRANSCRIPT_EXTENSIONS:
        raise UploadRejected(UploadRejectionReason.UNSUPPORTED_EXTENSION)


def check_size(size_bytes: int) -> None:
    if size_bytes < MIN_TRANSCRIPT_SIZE_BYTES:
        raise UploadRejected(UploadRejectionReason.EMPTY)

    if size_bytes > MAX_TRANSCRIPT_SIZE_BYTES:
        raise UploadRejected(UploadRejectionReason.TOO_LARGE)


def find_secret(text: str) -> SecretKind | None:
    for kind, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return kind

    return None


def check_content(*, filename: str, content: bytes) -> None:
    """Raise UploadRejected unless the bytes are an allowed-size UTF-8 text file with no credential in it."""
    check_extension(filename)
    check_size(len(content))

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise UploadRejected(UploadRejectionReason.NOT_TEXT)

    # A NUL byte is valid UTF-8 but never appears in a text transcript, only in binary files.
    if "\x00" in text:
        raise UploadRejected(UploadRejectionReason.NOT_TEXT)

    secret_kind = find_secret(text)
    if secret_kind is not None:
        raise UploadRejected(UploadRejectionReason.CONTAINS_SECRET, secret_kind=secret_kind)
