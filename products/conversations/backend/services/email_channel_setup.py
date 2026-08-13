import re
from hashlib import sha256
from html import unescape
from urllib.parse import urlsplit

from django.utils import timezone

from products.conversations.backend.models import (
    EmailChannel,
    EmailChannelConnectionStatus,
    EmailChannelSetup,
    EmailChannelSetupProvider,
)
from products.conversations.backend.services.email_thread_ingestion import ParsedInboundEmail

_GOOGLE_FORWARDING_SENDER = "forwarding-noreply@google.com"
_GOOGLE_DKIM_DOMAIN = "google.com"
_GOOGLE_CONFIRMATION_HOSTS = {"mail.google.com", "mail-settings.google.com"}
_GOOGLE_CONFIRMATION_PATH_PREFIX = "/mail/vf-"
_GOOGLE_FORWARDING_SUBJECT_RE = re.compile(
    r"^(?:(?:\(#\d+\)\s*)?Gmail|\([^\r\n]{1,100}) Forwarding Confirmation\s*-\s*Receive Mail from\s+"
    r"(?P<source>[^\s<>()]+@[^\s<>()]+)\)?\s*$",
    re.IGNORECASE,
)
_HTTPS_URL_RE = re.compile(r"https://[^\s<>\"']+", re.IGNORECASE)


def _google_source_email(email: ParsedInboundEmail) -> str | None:
    match = _GOOGLE_FORWARDING_SUBJECT_RE.fullmatch(email.subject.strip())
    if match is None:
        return None
    return match.group("source").lower()


def _validated_google_action(email: ParsedInboundEmail) -> str | None:
    candidates: set[str] = set()
    for raw_candidate in _HTTPS_URL_RE.findall(f"{email.body_plain}\n{email.stripped_text}"):
        candidate = unescape(raw_candidate).rstrip(".,);]}")
        try:
            parsed = urlsplit(candidate)
            port = parsed.port
        except ValueError:
            continue
        if (
            parsed.scheme.lower() != "https"
            or parsed.hostname is None
            or parsed.hostname.rstrip(".").lower() not in _GOOGLE_CONFIRMATION_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or not parsed.path.startswith(_GOOGLE_CONFIRMATION_PATH_PREFIX)
        ):
            continue
        candidates.add(candidate)
    if len(candidates) != 1:
        return None
    return next(iter(candidates))


def _is_google_authenticated(email: ParsedInboundEmail) -> bool:
    return (
        email.sender.email == _GOOGLE_FORWARDING_SENDER
        and email.sender_authenticated
        and email.dkim_passed
        and set(email.dkim_signing_domains) == {_GOOGLE_DKIM_DOMAIN}
    )


def capture_google_forwarding_confirmation(
    *,
    team_id: int,
    channel: EmailChannel,
    email: ParsedInboundEmail,
) -> bool:
    if channel.connection_status != EmailChannelConnectionStatus.PENDING_CONFIRMATION:
        return False

    expected_capture_prefix = f"team-{channel.inbound_token}@"
    if not email.capture_address.startswith(expected_capture_prefix):
        return False

    now = timezone.now()
    setup = (
        EmailChannelSetup.objects.for_team(team_id)
        .filter(
            channel_id=channel.id,
            provider=EmailChannelSetupProvider.GOOGLE,
        )
        .first()
    )
    if setup is None:
        return False
    if setup.expires_at <= now:
        EmailChannelSetup.objects.for_team(team_id).filter(id=setup.id, expires_at__lte=now).delete()
        EmailChannel.objects.filter(
            id=channel.id,
            team_id=team_id,
            connection_status=EmailChannelConnectionStatus.PENDING_CONFIRMATION,
        ).update(connection_status=EmailChannelConnectionStatus.CONFIRMATION_EXPIRED)
        return False

    if not _is_google_authenticated(email):
        return False
    if _google_source_email(email) != channel.from_email.lower():
        return False
    confirmation_action = _validated_google_action(email)
    if confirmation_action is None:
        return False

    updated = (
        EmailChannelSetup.objects.for_team(team_id)
        .filter(
            id=setup.id,
            channel_id=channel.id,
            channel__connection_status=EmailChannelConnectionStatus.PENDING_CONFIRMATION,
            expires_at__gt=now,
            confirmation_action__isnull=True,
        )
        .update(
            confirmation_action=confirmation_action,
            confirmation_message_id_hash=sha256(email.message_id.encode()).hexdigest(),
            confirmation_received_at=now,
        )
    )
    return updated == 1
