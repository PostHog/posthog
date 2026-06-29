"""Download and re-host Microsoft Teams image attachments into UploadedMedia.

Two entry points mirror the two inbound transports:
- ``extract_teams_bot_attachments`` — bot-framework webhook ``activity.attachments``
- ``extract_teams_graph_images`` — Graph chatMessage ``hostedContents``
"""

import re
from typing import Any
from urllib.parse import urlparse

import requests
import structlog

from posthog.models.team.team import Team

from .services.attachments import CONVERSATIONS_MAX_IMAGE_BYTES, is_valid_image, save_file_to_uploaded_media
from .support_teams import is_trusted_teams_service_url

logger = structlog.get_logger(__name__)

TEAMS_DOWNLOAD_TIMEOUT_SECONDS = 15

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_HOST = "graph.microsoft.com"

_RE_HOSTED_CONTENT_SRC = re.compile(
    r'<img[^>]+src="(https://graph\.microsoft\.com/[^"]*hostedContents/[^"]*)"',
    re.IGNORECASE,
)


def _is_graph_url(url: str) -> bool:
    """Return True iff `url` is HTTPS and hosted on graph.microsoft.com."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return host == GRAPH_HOST or host.endswith(f".{GRAPH_HOST}")


def _download_image(url: str, token: str) -> bytes | None:
    """Fetch image bytes from an auth-gated URL. Returns None on any failure.

    Redirects are disabled: the bearer token is privileged and the source URL
    originates from unsigned payload fields, so we never follow a hop to a host
    we didn't validate up front (mirrors the Slack downloader's redirect guard).
    """
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=TEAMS_DOWNLOAD_TIMEOUT_SECONDS,
            stream=True,
            allow_redirects=False,
        )
    except requests.RequestException:
        logger.warning("teams_image_download_error", url=url[:200])
        return None

    if resp.is_redirect or resp.is_permanent_redirect:
        logger.warning("teams_image_download_redirect_blocked", url=url[:200], status=resp.status_code)
        return None

    if resp.status_code != 200:
        logger.warning("teams_image_download_non_200", url=url[:200], status=resp.status_code)
        return None

    content_length = resp.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > CONVERSATIONS_MAX_IMAGE_BYTES:
                logger.warning("teams_image_too_large_header", url=url[:200], content_length=content_length)
                return None
        except ValueError:
            pass

    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=64 * 1024):
        total += len(chunk)
        if total > CONVERSATIONS_MAX_IMAGE_BYTES:
            logger.warning("teams_image_too_large_body", url=url[:200], bytes_read=total)
            return None
        chunks.append(chunk)

    return b"".join(chunks)


def _save_image(team: Team, image_bytes: bytes, name: str, mimetype: str) -> dict[str, Any] | None:
    """Validate and persist image bytes, returning the image dict or None."""
    if not is_valid_image(image_bytes):
        logger.warning("teams_image_invalid_content", name=name)
        return None

    stored_url = save_file_to_uploaded_media(team, name, mimetype, image_bytes, validate_images=False)
    if not stored_url:
        return None

    return {"url": stored_url, "name": name, "mimetype": mimetype}


def extract_teams_bot_attachments(
    attachments: list[dict[str, Any]] | None,
    team: Team,
    bot_token: str,
) -> list[dict[str, Any]]:
    """Extract image attachments from a bot-framework activity and re-host them."""
    if not attachments:
        return []

    images: list[dict[str, Any]] = []
    for att in attachments:
        content_type = att.get("contentType") or ""
        if not content_type.startswith("image/"):
            continue

        content_url = att.get("contentUrl") or ""
        if not content_url:
            continue

        # contentUrl is unsigned payload data; only send the bot token to hosts
        # we trust (Bot Framework / Teams service endpoints).
        if not is_trusted_teams_service_url(content_url):
            logger.warning("teams_bot_attachment_untrusted_host", url=content_url[:200])
            continue

        image_bytes = _download_image(content_url, bot_token)
        if not image_bytes:
            continue

        name = att.get("name") or "image"
        result = _save_image(team, image_bytes, name, content_type)
        if result:
            images.append(result)

    return images


def extract_teams_graph_images(
    msg: dict[str, Any],
    team: Team,
    teams_team_id: str,
    channel_id: str,
    token: str,
) -> list[dict[str, Any]]:
    """Extract hostedContents images from a Graph chatMessage and re-host them.

    Graph inline images appear as ``<img src="...hostedContents/{id}/$value">``
    in ``body.content``. The src URL requires a Graph token to fetch.

    The URL path is validated against the expected teams_team_id, channel_id,
    and message id to prevent a confused-deputy attack where crafted HTML
    could make us fetch arbitrary hostedContents the Graph token can read.
    """
    body = msg.get("body") or {}
    html_content = body.get("content") or ""

    src_urls = _RE_HOSTED_CONTENT_SRC.findall(html_content)
    if not src_urls:
        return []

    msg_id = msg.get("id") or ""

    hosted_contents = msg.get("hostedContents") or []
    hosted_map: dict[str, dict[str, Any]] = {}
    for hc in hosted_contents:
        hc_id = hc.get("id")
        if hc_id:
            hosted_map[hc_id] = hc

    images: list[dict[str, Any]] = []
    for idx, src_url in enumerate(src_urls):
        if not _is_graph_url(src_url):
            logger.warning("teams_graph_image_untrusted_host", url=src_url[:200])
            continue

        if not _is_expected_hosted_content_path(src_url, teams_team_id, channel_id, msg_id):
            logger.warning("teams_graph_image_path_mismatch", url=src_url[:200], msg_id=msg_id)
            continue

        image_bytes = _download_image(src_url, token)
        if not image_bytes:
            continue

        name = f"image_{idx + 1}"
        mimetype = "image/png"
        hc_id = _extract_hosted_content_id(src_url)
        if hc_id and hc_id in hosted_map:
            hc = hosted_map[hc_id]
            mimetype = hc.get("contentType") or mimetype

        result = _save_image(team, image_bytes, name, mimetype)
        if result:
            images.append(result)

    return images


_RE_GRAPH_HOSTED_PATH = re.compile(
    r"^/(?:v1\.0|beta)/teams/(?P<tid>[^/]+)/channels/(?P<cid>[^/]+)"
    r"/messages/(?P<mid>[^/]+)"
    r"(?:/replies/(?P<rid>[^/]+))?"
    r"/hostedcontents/[^/]+/\$value$",
    re.IGNORECASE,
)


def _is_expected_hosted_content_path(url: str, teams_team_id: str, channel_id: str, msg_id: str) -> bool:
    """Validate that a hostedContents URL belongs to the expected team/channel/message.

    Parses the path positionally against the exact Graph API structure:
        /v1.0/teams/{tid}/channels/{cid}/messages/{mid}/hostedContents/{hcid}/$value
        /v1.0/teams/{tid}/channels/{cid}/messages/{root}/replies/{rid}/hostedContents/{hcid}/$value
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    m = _RE_GRAPH_HOSTED_PATH.match(parsed.path)
    if not m:
        return False

    if m.group("tid").lower() != teams_team_id.lower():
        return False
    if m.group("cid").lower() != channel_id.lower():
        return False

    # For a top-level message, msg_id must match the messages segment.
    # For a reply, msg_id must match the replies segment.
    mid_lower = msg_id.lower()
    rid = m.group("rid")
    if rid:
        if rid.lower() != mid_lower:
            return False
    else:
        if m.group("mid").lower() != mid_lower:
            return False

    return True


def _extract_hosted_content_id(url: str) -> str | None:
    """Pull the hostedContent id from a Graph hostedContents URL."""
    marker = "hostedcontents/"
    url_lower = url.lower()
    idx = url_lower.find(marker)
    if idx == -1:
        return None
    rest = url[idx + len(marker) :]
    end = rest.find("/")
    if end == -1:
        return rest or None
    return rest[:end] or None
