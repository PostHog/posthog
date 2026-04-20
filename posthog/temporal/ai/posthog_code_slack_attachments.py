"""Cloud-prompt encoder for Slack file attachments forwarded to the PostHog Code agent.

Downloads files attached to a Slack `app_mention` event using the bot's token and
produces a string that the agent (posthog/code) understands: either the raw message
text (no attachments) or a `__twig_cloud_prompt_v1__:` prefixed JSON payload with
ACP `ContentBlock`s. The wire format is consumed by `deserializeCloudPrompt` in
`packages/agent/src/server/agent-server.ts` on the agent side.
"""

import json
import base64
from typing import Any
from urllib.parse import quote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

import structlog

logger = structlog.get_logger(__name__)

CLOUD_PROMPT_PREFIX = "__twig_cloud_prompt_v1__:"
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
SLACK_DOWNLOAD_TIMEOUT_SECONDS = 15
MAX_REDIRECTS = 5
ALLOWED_HOST_SUFFIXES = ("slack.com", "slack-edge.com", "slack-files.com")

_TEXT_MIME_PREFIXES = ("text/",)
_TEXT_MIME_EXTRAS = frozenset(
    {
        "application/json",
        "application/ld+json",
        "application/xml",
        "application/javascript",
        "application/typescript",
        "application/x-yaml",
        "application/yaml",
        "application/toml",
        "application/sql",
        "application/x-sh",
        "application/x-python",
        "application/x-shellscript",
        "application/x-ndjson",
    }
)


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _is_allowed_slack_file_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if parsed.scheme != "https":
        return False
    return any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in ALLOWED_HOST_SUFFIXES)


def _download_slack_file(url: str, bot_token: str) -> bytes | None:
    if not _is_allowed_slack_file_url(url):
        logger.warning("posthog_code_attachment_invalid_host", url=url)
        return None

    opener = build_opener(_NoRedirectHandler)
    next_url = url

    for _ in range(MAX_REDIRECTS + 1):
        request = Request(next_url, headers={"Authorization": f"Bearer {bot_token}"})
        with opener.open(request, timeout=SLACK_DOWNLOAD_TIMEOUT_SECONDS) as response:
            status = response.getcode()
            if status in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    return None
                redirect_url = urljoin(next_url, location)
                if not _is_allowed_slack_file_url(redirect_url):
                    logger.warning("posthog_code_attachment_invalid_redirect_host", url=redirect_url)
                    return None
                next_url = redirect_url
                continue

            if status != 200:
                logger.warning("posthog_code_attachment_download_non_200", url=next_url, status=status)
                return None

            content_length_header = response.headers.get("Content-Length")
            if content_length_header:
                try:
                    if int(content_length_header) > MAX_ATTACHMENT_BYTES:
                        logger.warning(
                            "posthog_code_attachment_too_large",
                            content_length=int(content_length_header),
                            max_allowed=MAX_ATTACHMENT_BYTES,
                        )
                        return None
                except ValueError:
                    return None

            payload = response.read(MAX_ATTACHMENT_BYTES + 1)
            if len(payload) > MAX_ATTACHMENT_BYTES:
                logger.warning("posthog_code_attachment_too_large_body", max_allowed=MAX_ATTACHMENT_BYTES)
                return None
            return payload

    logger.warning("posthog_code_attachment_too_many_redirects", url=url, max_redirects=MAX_REDIRECTS)
    return None


def _normalize_mime(mime: str | None) -> str:
    return (mime or "").lower().split(";")[0].strip()


def _is_text_mime(mime: str) -> bool:
    if not mime:
        return False
    if any(mime.startswith(prefix) for prefix in _TEXT_MIME_PREFIXES):
        return True
    return mime in _TEXT_MIME_EXTRAS


def _is_image_mime(mime: str) -> bool:
    return mime.startswith("image/") if mime else False


def _attachment_uri(file_id: str, filename: str) -> str:
    safe_id = file_id or "unknown"
    return f"attachment://{safe_id}?label={quote(filename or 'attachment', safe='')}"


def _build_content_block(file: dict[str, Any], bot_token: str) -> dict[str, Any] | None:
    file_id = str(file.get("id") or "")
    filename = file.get("name") or "attachment"
    mime = _normalize_mime(file.get("mimetype"))
    source_url = file.get("url_private_download") or file.get("url_private")
    if not source_url:
        logger.warning("posthog_code_attachment_missing_url", file_id=file_id)
        return None

    try:
        payload = _download_slack_file(source_url, bot_token)
    except Exception as exc:
        logger.warning("posthog_code_attachment_download_failed", file_id=file_id, error=str(exc))
        return None

    if payload is None:
        return None

    uri = _attachment_uri(file_id, filename)

    if _is_image_mime(mime):
        return {
            "type": "image",
            "uri": uri,
            "data": base64.b64encode(payload).decode("ascii"),
            "mimeType": mime,
        }

    if _is_text_mime(mime):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            return {
                "type": "resource",
                "resource": {
                    "uri": uri,
                    "text": text,
                    "mimeType": "text/plain",
                },
            }

    return {
        "type": "resource",
        "resource": {
            "uri": uri,
            "blob": base64.b64encode(payload).decode("ascii"),
            "mimeType": mime or "application/octet-stream",
        },
    }


def encode_user_message_with_attachments(
    text: str,
    files: list[dict[str, Any]] | None,
    bot_token: str | None,
) -> str:
    """Encode a Slack user message (plus any file attachments) for the PostHog Code agent.

    If no files are present, or the bot token is missing, or every download fails, the
    plain text is returned unchanged. Otherwise a `__twig_cloud_prompt_v1__:` prefixed
    JSON payload with one `text` block followed by one block per successfully
    downloaded attachment is returned.
    """
    if not files or not bot_token:
        return text

    file_blocks: list[dict[str, Any]] = []
    for file in files:
        if not isinstance(file, dict):
            continue
        block = _build_content_block(file, bot_token)
        if block is not None:
            file_blocks.append(block)

    if not file_blocks:
        return text

    blocks: list[dict[str, Any]] = []
    if text:
        blocks.append({"type": "text", "text": text})
    blocks.extend(file_blocks)

    return CLOUD_PROMPT_PREFIX + json.dumps({"blocks": blocks})
