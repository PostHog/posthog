import os
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import structlog

from posthog.egress.slack.transport import slack_request

from products.slack_app.backend.services.slack_messages import SlackFileRef, SlackThreadMessage

logger = structlog.get_logger(__name__)

MAX_SLACK_ATTACHMENTS_PER_MESSAGE = 15
# What the rest of the thread may contribute, on top of the triggering message's own.
# A thread accumulates screenshots over its life, most of them settled business by the
# time somebody asks a new question, and each one costs a download and a slot in the
# agent's workspace. The oldest survive the cap: the file being discussed is usually
# the one the thread opened with.
MAX_SLACK_ATTACHMENTS_PER_THREAD = 15
MAX_SLACK_ATTACHMENT_BYTES = 10 * 1024 * 1024
SLACK_DOWNLOAD_TIMEOUT_SECONDS = 15
MAX_SLACK_DOWNLOAD_REDIRECTS = 5

# What one turn may spend fetching attachments, across the triggering message and the
# rest of the thread together. The per-file caps above bound a single download, but the
# file counts multiply them: without these two budgets a turn could hold every payload
# in memory at once, and could stay in the download loop past the activity's
# `start_to_close` deadline, which fails the turn and repeats the whole batch on retry.
# Both are sized well under the activity deadline and the worker's memory, and a turn
# that reaches either one reports the remaining files as skipped instead of failing.
MAX_SLACK_ATTACHMENT_TOTAL_BYTES = 50 * 1024 * 1024
SLACK_ATTACHMENT_BATCH_SECONDS = 240

_MAX_ATTACHMENT_NAME_CHARS = 120

_ALLOWED_SLACK_FILE_HOST_SUFFIXES = ("slack.com", "slack-edge.com", "slack-files.com")

# Allowlist, not denylist: a wrongly blocked file produces a visible "skipped
# because…" note the user can act on, while a wrongly allowed file is silent.
# The realistic Slack-attachment set is small — images, PDFs, and plain-text
# data formats. Anything executable, scripted, or macro-capable stays out.
_ALLOWED_EXTENSIONS = frozenset(
    {
        ".bmp",
        ".csv",
        ".gif",
        ".jpeg",
        ".jpg",
        ".json",
        ".log",
        ".markdown",
        ".md",
        ".pdf",
        ".png",
        ".tsv",
        ".txt",
        ".webp",
        ".yaml",
        ".yml",
    }
)
_ALLOWED_MIME_TYPES = frozenset(
    {
        "application/json",
        "application/pdf",
        "application/x-yaml",
        "application/yaml",
        "image/bmp",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/csv",
        "text/markdown",
        "text/plain",
        "text/tab-separated-values",
        "text/yaml",
    }
)
_ALLOWED_SLACK_FILETYPES = frozenset(
    {
        "bmp",
        "csv",
        "gif",
        "jpeg",
        "jpg",
        "json",
        "markdown",
        "pdf",
        "png",
        "text",
        "tsv",
        "webp",
        "yaml",
    }
)

_ATTACHMENT_TYPE_SKIP_REASON = (
    "only image, PDF, and plain-text attachments (logs, markdown, CSV, JSON, YAML) are supported"
)

_SLOW_BATCH_SKIP_MESSAGE = (
    "Some Slack attachment(s) were skipped because they took too long to fetch. "
    "Post the one you want the agent to look at."
)
_LARGE_BATCH_SKIP_MESSAGE = (
    "Some Slack attachment(s) were skipped because the thread's files are too large to send together. "
    "Post the one you want the agent to look at."
)

_EXECUTABLE_MAGIC_PREFIXES = (
    b"MZ",
    b"\x7fELF",
    b"\xcf\xfa\xed\xfe",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xfe\xed\xfa\xce",
    b"\xca\xfe\xba\xbe",
)


class SlackAttachmentBudget:
    """The bytes and the wall-clock time one turn may spend fetching Slack attachments.

    A turn draws attachments from more than one place (the message that tagged the app,
    then the rest of the thread), and the limits apply to their sum, so one budget is
    created per turn and passed to each fetch.
    """

    def __init__(
        self,
        *,
        max_total_bytes: int = MAX_SLACK_ATTACHMENT_TOTAL_BYTES,
        seconds: float = SLACK_ATTACHMENT_BATCH_SECONDS,
    ) -> None:
        self._remaining_bytes = max_total_bytes
        self._deadline = time.monotonic() + seconds

    # Methods rather than properties, because both answers change with the clock between
    # two reads and an attribute reads like it does not.
    def is_expired(self) -> bool:
        return time.monotonic() >= self._deadline

    def seconds_left(self) -> float:
        return max(0.0, self._deadline - time.monotonic())

    @property
    def remaining_bytes(self) -> int:
        return self._remaining_bytes

    def spend_bytes(self, count: int) -> None:
        self._remaining_bytes = max(0, self._remaining_bytes - count)


@dataclass(frozen=True)
class PreparedSlackAttachments:
    artifacts: list[dict[str, Any]]
    skipped_messages: list[str]
    requested_count: int

    @property
    def has_files(self) -> bool:
        return self.requested_count > 0


def get_slack_bot_token(slack: Any, integration: Any) -> str | None:
    token = getattr(integration, "access_token", None)
    if isinstance(token, str) and token:
        return token

    client = getattr(slack, "client", None)
    token = getattr(client, "token", None)
    return token if isinstance(token, str) and token else None


def _normalize_content_type(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.split(";")[0].strip().lower()


def attachment_display_name(file: SlackFileRef) -> str:
    """The one name an attachment is known by, in the prompt and as the uploaded artifact.

    Slack takes both `name` and `title` as free text from the uploader, and both reach the
    agent's prompt, so a name is untrusted input rendered into a trust boundary. Angle
    brackets and line breaks are removed because the prompt marks its background-context
    block with `<slack_thread_context>` tags: without this a participant could name a file
    so that it closes the block and their text lands where the agent is told the real
    request is. The length cap keeps one long name from crowding out the message it
    belongs to.

    The prompt and the artifact use the same string so the agent can match the file it
    is told about to the file in its workspace.
    """
    raw_name = file.name or file.title or file.id or "slack-attachment"
    name = " ".join(os.path.basename(raw_name).replace("<", "").replace(">", "").split())
    return name[:_MAX_ATTACHMENT_NAME_CHARS] or "slack-attachment"


def _is_allowed_slack_file_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if parsed.scheme != "https":
        return False
    return any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in _ALLOWED_SLACK_FILE_HOST_SUFFIXES)


def _is_allowed_metadata(filename: str, content_type: str, slack_filetype: str) -> bool:
    """Every signal present must be allowed, and at least one positive signal must exist.

    Fails closed on contradiction (a ``.png`` name with a script mimetype) and on
    files with no recognizable signal. ``application/octet-stream`` is treated as
    "no mimetype" — Slack falls back to it for perfectly safe uploads, so it neither
    allows nor blocks on its own.
    """
    extension = os.path.splitext(filename.lower())[1]
    filetype = slack_filetype.lower()
    extension_allowed = extension in _ALLOWED_EXTENSIONS
    mime_allowed = content_type in _ALLOWED_MIME_TYPES
    filetype_allowed = filetype in _ALLOWED_SLACK_FILETYPES
    if extension and not extension_allowed:
        return False
    if content_type and content_type != "application/octet-stream" and not mime_allowed:
        return False
    if filetype and not filetype_allowed:
        return False
    return extension_allowed or mime_allowed or filetype_allowed


def _is_dangerous_payload(payload: bytes) -> bool:
    stripped = payload.lstrip()
    if stripped.startswith(b"#!"):
        return True
    return any(payload.startswith(prefix) for prefix in _EXECUTABLE_MAGIC_PREFIXES)


def _source_url(file: SlackFileRef) -> str:
    return file.url_private_download or file.url_private


def _download_slack_file(url: str, bot_token: str, budget: SlackAttachmentBudget) -> bytes | None:
    next_url = url
    max_bytes = min(MAX_SLACK_ATTACHMENT_BYTES, budget.remaining_bytes)
    for _ in range(MAX_SLACK_DOWNLOAD_REDIRECTS + 1):
        if budget.is_expired():
            logger.warning("slack_attachment_download_deadline_reached")
            return None

        if not _is_allowed_slack_file_url(next_url):
            parsed = urlparse(next_url)
            logger.warning("slack_attachment_download_rejected_host", host=parsed.hostname)
            return None

        response = slack_request(
            "GET",
            next_url,
            source="slack_app_attachments",
            endpoint="files.download",
            app_id="posthog",
            headers={"Authorization": f"Bearer {bot_token}"},
            # `requests` applies a scalar timeout to the connect and to each socket read,
            # not to the whole response, so a slow-drip body can hold a streamed download
            # far past it. Clamping to what is left of the batch keeps one such download
            # from consuming time the remaining files need.
            timeout=min(SLACK_DOWNLOAD_TIMEOUT_SECONDS, budget.seconds_left()),
            allow_redirects=False,
            stream=True,
        )
        try:
            if response.is_redirect:
                location = response.headers.get("Location")
                if not location:
                    return None
                next_url = urljoin(next_url, location)
                continue

            if response.status_code != 200:
                logger.warning("slack_attachment_download_failed_status", status_code=response.status_code)
                return None

            # Slack answers HTTP 200 with an HTML login/interstitial page when the
            # token lacks files:read or the file is access-restricted. HTML is never
            # an allowed attachment type, so an HTML body is always the interstitial
            # — forwarding it would silently hand the agent a login page as the file.
            response_content_type = _normalize_content_type(response.headers.get("Content-Type"))
            if response_content_type in ("text/html", "application/xhtml+xml"):
                logger.warning("slack_attachment_download_html_interstitial", content_type=response_content_type)
                return None

            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        logger.warning("slack_attachment_download_rejected_size", content_length=content_length)
                        return None
                except ValueError:
                    return None

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                if budget.is_expired():
                    logger.warning("slack_attachment_download_deadline_reached_mid_body", total=total)
                    return None
                total += len(chunk)
                if total > max_bytes:
                    logger.warning("slack_attachment_download_rejected_body_size", total=total)
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()

    logger.warning("slack_attachment_download_too_many_redirects")
    return None


def _file_dedupe_key(file: SlackFileRef) -> str:
    """What identifies a file across the messages it appears in.

    Slack gives every upload a workspace-unique id that a re-share carries with it, so
    the id is the answer wherever there is one. The download url stands in for the rare
    file that arrives without one.
    """
    return file.id or _source_url(file)


def prepare_slack_file_artifacts(
    files: list[SlackFileRef],
    bot_token: str | None,
    *,
    budget: SlackAttachmentBudget | None = None,
) -> PreparedSlackAttachments:
    """Fetch the attachments on one Slack message, ready to upload to the agent's workspace."""
    return _prepare_files(
        files,
        bot_token,
        max_files=MAX_SLACK_ATTACHMENTS_PER_MESSAGE,
        over_limit_message=(
            f"Additional Slack attachment(s) skipped: only {MAX_SLACK_ATTACHMENTS_PER_MESSAGE} files are supported per message."
        ),
        budget=budget or SlackAttachmentBudget(),
    )


def prepare_slack_thread_file_artifacts(
    thread_messages: list[SlackThreadMessage],
    bot_token: str | None,
    *,
    already_requested: list[SlackFileRef] | None = None,
    budget: SlackAttachmentBudget | None = None,
) -> PreparedSlackAttachments:
    """Fetch the attachments posted elsewhere in the thread, oldest first.

    The message that tags the app is rarely the one carrying the screenshot — somebody
    posts a chart, the discussion runs, and the ask lands several replies later. Slack
    hands the agent no way to reach those files itself: ``url_private`` answers only to
    a workspace token, which is exactly what a sandbox does not hold. So the bot fetches
    them here, the same way it fetches the triggering message's own.

    ``already_requested`` is that triggering message's file list, whose attachments the
    caller prepares separately. Anything in it is left alone rather than downloaded twice.

    Pass the same ``budget`` the caller used for that separate fetch, so the two share one
    allowance rather than each getting a full one.
    """
    seen = {_file_dedupe_key(file) for file in already_requested or []}
    files: list[SlackFileRef] = []
    for message in thread_messages:
        for file in message.files:
            key = _file_dedupe_key(file)
            if key in seen:
                continue
            seen.add(key)
            files.append(file)

    return _prepare_files(
        files,
        bot_token,
        max_files=MAX_SLACK_ATTACHMENTS_PER_THREAD,
        over_limit_message=(
            f"Slack attachment(s) from earlier in the thread skipped: only {MAX_SLACK_ATTACHMENTS_PER_THREAD} "
            "thread files are supported."
        ),
        budget=budget or SlackAttachmentBudget(),
    )


def merge_prepared_attachments(*parts: PreparedSlackAttachments) -> PreparedSlackAttachments:
    """One set of attachments out of several, for a turn that draws on more than one message."""
    return PreparedSlackAttachments(
        artifacts=[artifact for part in parts for artifact in part.artifacts],
        skipped_messages=[message for part in parts for message in part.skipped_messages],
        requested_count=sum(part.requested_count for part in parts),
    )


def _prepare_files(
    files: list[SlackFileRef],
    bot_token: str | None,
    *,
    max_files: int,
    over_limit_message: str,
    budget: SlackAttachmentBudget,
) -> PreparedSlackAttachments:
    if not files:
        return PreparedSlackAttachments(artifacts=[], skipped_messages=[], requested_count=0)

    requested_count = len(files)
    if not bot_token:
        return PreparedSlackAttachments(
            artifacts=[],
            skipped_messages=["Slack attachment(s) could not be read because the Slack bot token was unavailable."],
            requested_count=requested_count,
        )

    artifacts: list[dict[str, Any]] = []
    skipped_messages: list[str] = []

    for index, file in enumerate(files):
        if index >= max_files:
            skipped_messages.append(over_limit_message)
            break
        if budget.is_expired():
            skipped_messages.append(_SLOW_BATCH_SKIP_MESSAGE)
            break
        if budget.remaining_bytes <= 0:
            skipped_messages.append(_LARGE_BATCH_SKIP_MESSAGE)
            break

        filename = attachment_display_name(file)
        content_type = _normalize_content_type(file.mimetype) or "application/octet-stream"
        if not _is_allowed_metadata(filename, content_type, file.filetype):
            skipped_messages.append(f"{filename} was skipped because {_ATTACHMENT_TYPE_SKIP_REASON}.")
            continue

        if file.size is not None and file.size > MAX_SLACK_ATTACHMENT_BYTES:
            skipped_messages.append(f"{filename} was skipped because it exceeds the 10 MB Slack attachment limit.")
            continue
        # Slack reports the size on nearly every upload, so stopping here reports the real
        # reason rather than starting a download the byte ceiling would abort part-way.
        if file.size is not None and file.size > budget.remaining_bytes:
            skipped_messages.append(_LARGE_BATCH_SKIP_MESSAGE)
            break

        url = _source_url(file)
        if not url:
            skipped_messages.append(f"{filename} was skipped because Slack did not provide a download URL.")
            continue
        if not _is_allowed_slack_file_url(url):
            skipped_messages.append(f"{filename} was skipped because its download URL was not a Slack file URL.")
            continue

        try:
            payload = _download_slack_file(url, bot_token, budget)
        except Exception:
            logger.exception("slack_attachment_download_exception", file_id=file.id)
            payload = None

        if payload is None:
            skipped_messages.append(f"{filename} was skipped because it could not be downloaded from Slack.")
            continue
        budget.spend_bytes(len(payload))
        if _is_dangerous_payload(payload):
            skipped_messages.append(f"{filename} was skipped because its content looks like an executable or script.")
            continue

        artifact: dict[str, Any] = {
            "name": filename,
            "type": "user_attachment",
            "source": "slack_user_attachment",
            "content_type": content_type,
            "content_bytes": payload,
        }
        # A deterministic id (keyed on Slack's globally-unique file id) makes the
        # manifest append an upsert: activity retries after a partial failure
        # re-upload to the same id instead of appending duplicate entries.
        if file.id:
            artifact["id"] = uuid.uuid5(uuid.NAMESPACE_URL, f"posthog:slack_user_attachment:{file.id}").hex
        artifacts.append(artifact)

    return PreparedSlackAttachments(
        artifacts=artifacts,
        skipped_messages=skipped_messages,
        requested_count=requested_count,
    )


def build_slack_attachment_prompt_text(
    message: str | None,
    *,
    uploaded_artifacts: list[dict[str, Any]],
    skipped_messages: list[str],
) -> str | None:
    pieces: list[str] = []
    if message:
        pieces.append(message)

    if uploaded_artifacts:
        names = ", ".join(str(artifact.get("name") or "attachment") for artifact in uploaded_artifacts)
        pieces.append(f"Slack attachment(s) available to the agent as task files: {names}.")

    if skipped_messages:
        skipped = "\n".join(f"- {msg}" for msg in skipped_messages)
        pieces.append(f"Slack attachment(s) skipped:\n{skipped}")

    return "\n\n".join(pieces) if pieces else None
