import re
import base64
import binascii
from collections.abc import Callable
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr
from html import unescape
from typing import Any

from django.utils import timezone
from django.utils.html import strip_tags

import requests

from posthog.dataclasses import frozen
from posthog.egress.google_workspace import google_workspace_request
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, Integration, OauthIntegration
from posthog.models.organization import OrganizationMembership

from products.conversations.backend.models import EmailChannel, EmailChannelKind, EmailThreadMessageDirection
from products.conversations.backend.services.email_thread_ingestion import (
    EmailAddress,
    ParsedEmail,
    ingest_customer_email,
)

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_HISTORY_ID_CONFIG_KEY = "gmail_history_id"
GMAIL_LAST_SYNCED_AT_CONFIG_KEY = "gmail_last_synced_at"
GMAIL_HISTORY_START_ID_CONFIG_KEY = "gmail_history_start_id"
GMAIL_HISTORY_PAGE_TOKEN_CONFIG_KEY = "gmail_history_page_token"
GMAIL_HISTORY_TARGET_ID_CONFIG_KEY = "gmail_history_target_id"
GMAIL_PENDING_MESSAGE_IDS_CONFIG_KEY = "gmail_pending_message_ids"
GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
INITIAL_IMPORT_QUERY = "{in:inbox in:sent} newer_than:30d"
INITIAL_IMPORT_LIMIT = 100
HISTORY_PAGE_SIZE = 100
HISTORY_MESSAGE_BATCH_SIZE = 100
MAX_ATTACHMENT_BACKED_BODY_PARTS = 4
_MESSAGE_ID_RE = re.compile(r"<[^<>\s]+>")


class GmailSyncError(Exception):
    pass


class _GmailBodyPartLimitExceeded(Exception):
    pass


@frozen
class _EmailBodies:
    plain: str
    html: str


def integration_has_gmail_scope(integration: Integration) -> bool:
    scopes = integration.config.get("scope") or ""
    return GMAIL_READONLY_SCOPE in scopes.split()


def sync_gmail_integration(integration_id: int, team_id: int) -> None:
    integration = Integration.objects.select_related("team", "created_by").get(
        id=integration_id,
        team_id=team_id,
        kind="google-calendar",
    )
    if not integration_has_gmail_scope(integration) or not _has_active_owner(integration):
        return

    access_token = _get_fresh_access_token(integration)
    channel = _email_channel(integration)
    internal_emails = _organization_member_emails(integration)
    history_id = integration.config.get(GMAIL_HISTORY_ID_CONFIG_KEY)

    if history_id:
        next_history_id = _sync_history(
            integration=integration,
            channel=channel,
            access_token=access_token,
            start_history_id=str(history_id),
            internal_emails=internal_emails,
        )
    else:
        next_history_id = _initial_sync(
            integration=integration,
            channel=channel,
            access_token=access_token,
            internal_emails=internal_emails,
        )

    if next_history_id is None:
        return

    integration.refresh_from_db(fields=["config"])
    integration.config[GMAIL_HISTORY_ID_CONFIG_KEY] = next_history_id
    integration.config[GMAIL_LAST_SYNCED_AT_CONFIG_KEY] = timezone.now().isoformat()
    integration.save(update_fields=["config"])


def _has_active_owner(integration: Integration) -> bool:
    owner = integration.created_by
    return bool(owner and owner.is_active and owner.teams.filter(id=integration.team_id).exists())


def _get_fresh_access_token(integration: Integration) -> str:
    oauth = OauthIntegration(integration)
    if integration.errors != ERROR_TOKEN_REFRESH_FAILED and oauth.access_token_expired():
        oauth.refresh_access_token()
    if integration.errors == ERROR_TOKEN_REFRESH_FAILED:
        raise GmailSyncError(f"Token refresh failed for integration {integration.id}")
    token = integration.access_token
    if not token:
        raise GmailSyncError(f"Integration {integration.id} has no access token")
    return token


def _email_channel(integration: Integration) -> EmailChannel:
    owner = integration.created_by
    email = str(integration.config.get("email") or "").strip().lower()
    if owner is None or not email or "@" not in email:
        raise GmailSyncError(f"Integration {integration.id} has no mailbox owner")

    name = " ".join(part for part in (owner.first_name, owner.last_name) if part).strip() or email
    return EmailChannel(
        team=integration.team,
        kind=EmailChannelKind.CUSTOMER_COMMUNICATION,
        owner=owner,
        inbound_token="",
        from_email=email,
        from_name=name,
        domain=email.rsplit("@", 1)[1],
        domain_verified=False,
        dns_records={},
        is_default=False,
    )


def _organization_member_emails(integration: Integration) -> set[str]:
    return {
        email.lower()
        for email in OrganizationMembership.objects.filter(
            organization_id=integration.team.organization_id,
            user__is_active=True,
        ).values_list("user__email", flat=True)
    }


def _initial_sync(
    *,
    integration: Integration,
    channel: EmailChannel,
    access_token: str,
    internal_emails: set[str],
) -> str:
    profile = _get_json(
        integration=integration,
        access_token=access_token,
        url=f"{GMAIL_API_BASE_URL}/profile",
        endpoint="/gmail/v1/users/me/profile",
    )
    history_id = str(profile.get("historyId") or "")
    if not history_id:
        raise GmailSyncError("Gmail profile did not include a history cursor")

    payload = _get_json(
        integration=integration,
        access_token=access_token,
        url=f"{GMAIL_API_BASE_URL}/messages",
        endpoint="/gmail/v1/users/me/messages",
        params={"q": INITIAL_IMPORT_QUERY, "maxResults": INITIAL_IMPORT_LIMIT},
    )
    _ingest_message_ids(
        integration=integration,
        channel=channel,
        access_token=access_token,
        message_ids=[str(message["id"]) for message in payload.get("messages", []) if message.get("id")],
        internal_emails=internal_emails,
    )
    return history_id


def _sync_history(
    *,
    integration: Integration,
    channel: EmailChannel,
    access_token: str,
    start_history_id: str,
    internal_emails: set[str],
) -> str | None:
    processed_messages = 0
    while processed_messages < HISTORY_MESSAGE_BATCH_SIZE:
        integration.refresh_from_db(fields=["config"])
        config = integration.config or {}
        progress_start_id = str(config.get(GMAIL_HISTORY_START_ID_CONFIG_KEY) or start_history_id)
        page_token = str(config.get(GMAIL_HISTORY_PAGE_TOKEN_CONFIG_KEY) or "") or None
        target_history_id = str(config.get(GMAIL_HISTORY_TARGET_ID_CONFIG_KEY) or "") or None
        pending_message_ids = [str(message_id) for message_id in config.get(GMAIL_PENDING_MESSAGE_IDS_CONFIG_KEY) or []]

        if pending_message_ids:
            _ingest_message_id(
                integration=integration,
                channel=channel,
                access_token=access_token,
                gmail_message_id=pending_message_ids[0],
                internal_emails=internal_emails,
            )
            _save_history_progress(
                integration,
                start_history_id=progress_start_id,
                page_token=page_token,
                target_history_id=target_history_id,
                pending_message_ids=pending_message_ids[1:],
            )
            processed_messages += 1
            continue

        if target_history_id and page_token is None:
            _clear_history_progress(integration)
            return target_history_id

        params = {
            "startHistoryId": progress_start_id,
            "historyTypes": "messageAdded",
            "maxResults": HISTORY_PAGE_SIZE,
        }
        if page_token:
            params["pageToken"] = page_token
        response = _request(
            integration=integration,
            access_token=access_token,
            url=f"{GMAIL_API_BASE_URL}/history",
            endpoint="/gmail/v1/users/me/history",
            params=params,
        )
        if response.status_code == 404:
            _clear_history_progress(integration)
            return _initial_sync(
                integration=integration,
                channel=channel,
                access_token=access_token,
                internal_emails=internal_emails,
            )
        payload = _response_json(response, "Gmail history")
        message_ids = list(
            dict.fromkeys(
                str(added["message"]["id"])
                for history in payload.get("history", [])
                for added in history.get("messagesAdded", [])
                if added.get("message", {}).get("id")
            )
        )
        _save_history_progress(
            integration,
            start_history_id=progress_start_id,
            page_token=str(payload.get("nextPageToken") or "") or None,
            target_history_id=str(payload.get("historyId") or target_history_id or progress_start_id),
            pending_message_ids=message_ids,
        )

    return None


def _save_history_progress(
    integration: Integration,
    *,
    start_history_id: str,
    page_token: str | None,
    target_history_id: str | None,
    pending_message_ids: list[str],
) -> None:
    integration.refresh_from_db(fields=["config"])
    integration.config[GMAIL_HISTORY_START_ID_CONFIG_KEY] = start_history_id
    integration.config[GMAIL_HISTORY_PAGE_TOKEN_CONFIG_KEY] = page_token
    integration.config[GMAIL_HISTORY_TARGET_ID_CONFIG_KEY] = target_history_id
    integration.config[GMAIL_PENDING_MESSAGE_IDS_CONFIG_KEY] = pending_message_ids
    integration.save(update_fields=["config"])


def _clear_history_progress(integration: Integration) -> None:
    integration.refresh_from_db(fields=["config"])
    for key in (
        GMAIL_HISTORY_START_ID_CONFIG_KEY,
        GMAIL_HISTORY_PAGE_TOKEN_CONFIG_KEY,
        GMAIL_HISTORY_TARGET_ID_CONFIG_KEY,
        GMAIL_PENDING_MESSAGE_IDS_CONFIG_KEY,
    ):
        integration.config.pop(key, None)
    integration.save(update_fields=["config"])


def _ingest_message_ids(
    *,
    integration: Integration,
    channel: EmailChannel,
    access_token: str,
    message_ids: list[str],
    internal_emails: set[str],
) -> None:
    for gmail_message_id in message_ids:
        _ingest_message_id(
            integration=integration,
            channel=channel,
            access_token=access_token,
            gmail_message_id=gmail_message_id,
            internal_emails=internal_emails,
        )


def _ingest_message_id(
    *,
    integration: Integration,
    channel: EmailChannel,
    access_token: str,
    gmail_message_id: str,
    internal_emails: set[str],
) -> None:
    payload = _get_json_allowing_missing(
        integration=integration,
        access_token=access_token,
        url=f"{GMAIL_API_BASE_URL}/messages/{gmail_message_id}",
        endpoint="/gmail/v1/users/me/messages/{message_id}",
        params={"format": "full"},
    )
    # The user deleted the message between the history page and this fetch. Skip it.
    if payload is None:
        return

    def load_attachment_data(attachment_id: str) -> str:
        attachment = _get_json_allowing_missing(
            integration=integration,
            access_token=access_token,
            url=f"{GMAIL_API_BASE_URL}/messages/{gmail_message_id}/attachments/{attachment_id}",
            endpoint="/gmail/v1/users/me/messages/{message_id}/attachments/{attachment_id}",
        )
        return str(attachment.get("data") or "") if attachment else ""

    try:
        parsed = _parse_gmail_message(
            payload,
            channel.from_email,
            str(integration.integration_id),
            load_attachment_data=load_attachment_data,
        )
    except _GmailBodyPartLimitExceeded:
        return
    if parsed is None or not _has_external_participant(parsed, internal_emails):
        return
    labels = set(payload.get("labelIds") or [])
    if not labels.intersection({"INBOX", "SENT"}):
        return
    direction = EmailThreadMessageDirection.OUTBOUND if "SENT" in labels else EmailThreadMessageDirection.INBOUND
    ingest_customer_email(
        team_id=integration.team_id,
        channel=channel,
        email=parsed,
        direction=direction,
        source_type="gmail",
        source_id=f"{integration.id}:{gmail_message_id}",
    )


def _parse_gmail_message(
    payload: dict[str, Any],
    mailbox_email: str,
    google_account_id: str,
    *,
    load_attachment_data: Callable[[str], str] | None = None,
) -> ParsedEmail | None:
    gmail_message_id = str(payload.get("id") or "")
    message_payload = payload.get("payload") or {}
    headers = _message_headers(message_payload.get("headers") or [])
    sender_name, sender_email = parseaddr(headers.get("from", ""))
    sender_email = sender_email.strip().lower()[:400]
    if not gmail_message_id or not sender_email:
        return None

    message_id = headers.get("message-id") or f"gmail:{google_account_id}:{gmail_message_id}"
    in_reply_to_ids = _parse_message_ids(headers.get("in-reply-to", ""))
    sent_at = _parse_internal_date(payload.get("internalDate"))
    bodies = _message_bodies(message_payload, load_attachment_data=load_attachment_data)
    body_plain = bodies.plain
    if not body_plain and bodies.html:
        body_plain = unescape(strip_tags(bodies.html))

    return ParsedEmail(
        message_id=message_id[:998],
        in_reply_to=in_reply_to_ids[0] if in_reply_to_ids else None,
        references=_parse_message_ids(headers.get("references", "")),
        sent_at=sent_at,
        sender=EmailAddress(name=_decode_header(sender_name)[:400], email=sender_email),
        to_recipients=_parse_addresses(headers.get("to", "")),
        cc_recipients=_parse_addresses(headers.get("cc", "")),
        subject=_decode_header(headers.get("subject", ""))[:500],
        body_plain=body_plain[:50_000],
        stripped_text=body_plain[:50_000],
        sender_authenticated=False,
        dkim_passed=False,
        dkim_signing_domains=(),
        capture_address=mailbox_email,
        attachments=(),
    )


def _message_headers(raw_headers: list[dict[str, Any]]) -> dict[str, str]:
    values: dict[str, list[str]] = {}
    for header in raw_headers:
        name = str(header.get("name") or "").lower()
        value = str(header.get("value") or "")
        if name and value:
            values.setdefault(name, []).append(value)
    return {name: ", ".join(items) for name, items in values.items()}


def _decode_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeError):
        return value


def _parse_message_ids(value: str) -> tuple[str, ...]:
    message_ids = _MESSAGE_ID_RE.findall(value)
    if not message_ids:
        message_ids = value.split()
    return tuple(dict.fromkeys(message_id.strip()[:998] for message_id in message_ids if message_id.strip()))


def _parse_addresses(value: str) -> tuple[EmailAddress, ...]:
    addresses: list[EmailAddress] = []
    seen: set[str] = set()
    for name, email in getaddresses([value]):
        normalized = email.strip().lower()[:400]
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        addresses.append(EmailAddress(name=_decode_header(name)[:400], email=normalized))
    return tuple(addresses)


def _parse_internal_date(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(str(value)) / 1000, tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return timezone.now()


def _message_bodies(
    payload: dict[str, Any],
    *,
    load_attachment_data: Callable[[str], str] | None = None,
) -> _EmailBodies:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachment_backed_body_parts = 0

    def visit(part: dict[str, Any]) -> None:
        nonlocal attachment_backed_body_parts
        mime_type = str(part.get("mimeType") or "").lower()
        body = part.get("body") or {}
        data = str(body.get("data") or "")
        attachment_id = str(body.get("attachmentId") or "")
        if mime_type in ("text/plain", "text/html") and not data and attachment_id and load_attachment_data:
            if attachment_backed_body_parts >= MAX_ATTACHMENT_BACKED_BODY_PARTS:
                raise _GmailBodyPartLimitExceeded
            attachment_backed_body_parts += 1
            data = load_attachment_data(attachment_id)
        decoded = _decode_body(data)
        if decoded and mime_type == "text/plain":
            plain_parts.append(decoded)
        elif decoded and mime_type == "text/html":
            html_parts.append(decoded)
        for child in part.get("parts") or []:
            visit(child)

    visit(payload)
    return _EmailBodies(
        plain="\n".join(plain_parts).strip(),
        html="\n".join(html_parts).strip(),
    )


def _decode_body(data: str) -> str:
    if not data:
        return ""
    try:
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except (ValueError, binascii.Error):
        return ""


def _has_external_participant(email: ParsedEmail, internal_emails: set[str]) -> bool:
    addresses = {
        email.sender.email,
        *(recipient.email for recipient in email.to_recipients),
        *(recipient.email for recipient in email.cc_recipients),
    }
    return any(address and address not in internal_emails for address in addresses)


def _request(
    *,
    integration: Integration,
    access_token: str,
    url: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
) -> requests.Response:
    return google_workspace_request(
        "GET",
        url,
        access_token=access_token,
        account_id=str(integration.integration_id),
        source="customer_analytics",
        endpoint=endpoint,
        params=params,
        timeout=30,
    )


def _get_json(
    *,
    integration: Integration,
    access_token: str,
    url: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = _request(
        integration=integration,
        access_token=access_token,
        url=url,
        endpoint=endpoint,
        params=params,
    )
    return _response_json(response, "Gmail API")


def _get_json_allowing_missing(
    *,
    integration: Integration,
    access_token: str,
    url: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    response = _request(
        integration=integration,
        access_token=access_token,
        url=url,
        endpoint=endpoint,
        params=params,
    )
    if response.status_code == 404:
        return None
    return _response_json(response, "Gmail API")


def _response_json(response: requests.Response, operation: str) -> dict[str, Any]:
    if response.status_code != 200:
        raise GmailSyncError(f"{operation} returned {response.status_code}: {response.text[:200]}")
    try:
        payload = response.json()
    except ValueError as error:
        raise GmailSyncError(f"{operation} returned an invalid response") from error
    if not isinstance(payload, dict):
        raise GmailSyncError(f"{operation} returned an invalid response")
    return payload
