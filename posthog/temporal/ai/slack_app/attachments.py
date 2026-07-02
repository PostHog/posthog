import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
import structlog

logger = structlog.get_logger(__name__)

MAX_SLACK_ATTACHMENTS_PER_MESSAGE = 5
MAX_SLACK_ATTACHMENT_BYTES = 10 * 1024 * 1024
SLACK_DOWNLOAD_TIMEOUT_SECONDS = 15
MAX_SLACK_DOWNLOAD_REDIRECTS = 5

_ALLOWED_SLACK_FILE_HOST_SUFFIXES = ("slack.com", "slack-edge.com", "slack-files.com")
_DANGEROUS_EXTENSIONS = frozenset(
    {
        ".app",
        ".apk",
        ".bat",
        ".bin",
        ".bash",
        ".cmd",
        ".com",
        ".cpl",
        ".csh",
        ".dll",
        ".dmg",
        ".elf",
        ".exe",
        ".fish",
        ".hta",
        ".jar",
        ".js",
        ".jse",
        ".ksh",
        ".lnk",
        ".mjs",
        ".msi",
        ".pkg",
        ".pif",
        ".ps1",
        ".psd1",
        ".psm1",
        ".py",
        ".rb",
        ".reg",
        ".run",
        ".scr",
        ".sh",
        ".vb",
        ".vbe",
        ".vbs",
        ".wsf",
        ".wsh",
        ".zsh",
    }
)
_DANGEROUS_MIME_TYPES = frozenset(
    {
        "application/bat",
        "application/cmd",
        "application/com",
        "application/dos-exe",
        "application/exe",
        "application/javascript",
        "application/java-archive",
        "application/msdos-windows",
        "application/octet-stream-executable",
        "application/vnd.microsoft.portable-executable",
        "application/x-apple-diskimage",
        "application/x-bat",
        "application/x-csh",
        "application/x-dosexec",
        "application/x-executable",
        "application/x-ms-dos-executable",
        "application/x-msdownload",
        "application/x-msi",
        "application/x-powershell",
        "application/x-python",
        "application/x-ruby",
        "application/x-sh",
        "application/x-shellscript",
        "application/x-zsh",
        "text/javascript",
        "text/x-python",
        "text/x-ruby",
        "text/x-script.python",
        "text/x-shellscript",
        "text/x-sh",
    }
)
_DANGEROUS_SLACK_FILETYPES = frozenset(
    {
        "applescript",
        "binary",
        "csh",
        "executable",
        "javascript",
        "js",
        "ksh",
        "powershell",
        "python",
        "ruby",
        "shell",
        "sh",
        "vb",
        "vbscript",
        "zsh",
    }
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


def _safe_filename(file: dict[str, Any]) -> str:
    raw_name = file.get("name") or file.get("title") or file.get("id") or "slack-attachment"
    name = os.path.basename(str(raw_name)).strip()
    return name or "slack-attachment"


def _is_allowed_slack_file_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if parsed.scheme != "https":
        return False
    return any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in _ALLOWED_SLACK_FILE_HOST_SUFFIXES)


def _is_dangerous_metadata(filename: str, content_type: str, slack_filetype: Any) -> bool:
    extension = os.path.splitext(filename.lower())[1]
    if extension in _DANGEROUS_EXTENSIONS:
        return True
    if content_type in _DANGEROUS_MIME_TYPES:
        return True
    return isinstance(slack_filetype, str) and slack_filetype.lower() in _DANGEROUS_SLACK_FILETYPES


def _is_dangerous_payload(payload: bytes) -> bool:
    stripped = payload.lstrip()
    if stripped.startswith(b"#!"):
        return True
    return any(payload.startswith(prefix) for prefix in _EXECUTABLE_MAGIC_PREFIXES)


def _source_url(file: dict[str, Any]) -> str | None:
    url = file.get("url_private_download") or file.get("url_private")
    return url if isinstance(url, str) and url else None


def _file_size(file: dict[str, Any]) -> int | None:
    size = file.get("size")
    if isinstance(size, int) and not isinstance(size, bool):
        return size
    if isinstance(size, str):
        try:
            return int(size)
        except ValueError:
            return None
    return None


def _download_slack_file(url: str, bot_token: str) -> bytes | None:
    next_url = url
    for _ in range(MAX_SLACK_DOWNLOAD_REDIRECTS + 1):
        if not _is_allowed_slack_file_url(next_url):
            parsed = urlparse(next_url)
            logger.warning("slack_attachment_download_rejected_host", host=parsed.hostname)
            return None

        response = requests.get(
            next_url,
            headers={"Authorization": f"Bearer {bot_token}"},
            timeout=SLACK_DOWNLOAD_TIMEOUT_SECONDS,
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

            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > MAX_SLACK_ATTACHMENT_BYTES:
                        logger.warning("slack_attachment_download_rejected_size", content_length=content_length)
                        return None
                except ValueError:
                    return None

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_SLACK_ATTACHMENT_BYTES:
                    logger.warning("slack_attachment_download_rejected_body_size", total=total)
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()

    logger.warning("slack_attachment_download_too_many_redirects")
    return None


def prepare_slack_file_artifacts(files: Any, bot_token: str | None) -> PreparedSlackAttachments:
    if not isinstance(files, list) or not files:
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
        if index >= MAX_SLACK_ATTACHMENTS_PER_MESSAGE:
            skipped_messages.append(
                f"Additional Slack attachment(s) skipped: only {MAX_SLACK_ATTACHMENTS_PER_MESSAGE} files are supported per message."
            )
            break
        if not isinstance(file, dict):
            skipped_messages.append("A Slack attachment was skipped because its metadata was invalid.")
            continue

        filename = _safe_filename(file)
        content_type = _normalize_content_type(file.get("mimetype")) or "application/octet-stream"
        if _is_dangerous_metadata(filename, content_type, file.get("filetype")):
            skipped_messages.append(f"{filename} was skipped because executable or script attachments are not allowed.")
            continue

        size = _file_size(file)
        if size is not None and size > MAX_SLACK_ATTACHMENT_BYTES:
            skipped_messages.append(f"{filename} was skipped because it exceeds the 10 MB Slack attachment limit.")
            continue

        url = _source_url(file)
        if not url:
            skipped_messages.append(f"{filename} was skipped because Slack did not provide a download URL.")
            continue
        if not _is_allowed_slack_file_url(url):
            skipped_messages.append(f"{filename} was skipped because its download URL was not a Slack file URL.")
            continue

        try:
            payload = _download_slack_file(url, bot_token)
        except Exception:
            logger.exception("slack_attachment_download_exception", file_id=file.get("id"))
            payload = None

        if payload is None:
            skipped_messages.append(f"{filename} was skipped because it could not be downloaded from Slack.")
            continue
        if _is_dangerous_payload(payload):
            skipped_messages.append(f"{filename} was skipped because executable or script attachments are not allowed.")
            continue

        artifacts.append(
            {
                "name": filename,
                "type": "user_attachment",
                "source": "slack_user_attachment",
                "content_type": content_type,
                "content_bytes": payload,
            }
        )

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
