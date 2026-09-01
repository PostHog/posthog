import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from hashlib import sha256
from html import unescape
from urllib.parse import urlsplit
from uuid import UUID

from django.core import signing
from django.db import transaction
from django.utils import timezone

from products.conversations.backend.models import (
    EmailChannel,
    EmailChannelConnectionStatus,
    EmailChannelKind,
    EmailChannelSetup,
    EmailChannelSetupProvider,
)
from products.conversations.backend.services.email_thread_ingestion import ParsedEmail

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

CUSTOMER_EMAIL_SETUP_TTL = timedelta(hours=24)
FORWARDING_CHALLENGE_HEADER = "X-PostHog-Forwarding-Challenge"
FORWARDING_CHALLENGE_MARKER = "posthog-forwarding-challenge:"
FORWARDING_CHALLENGE_MAX_AGE_SECONDS = int(CUSTOMER_EMAIL_SETUP_TTL.total_seconds())
_FORWARDING_CHALLENGE_PURPOSE = "customer-email-forwarding"
_FORWARDING_CHALLENGE_SALT = "products.conversations.customer-email-forwarding"


@dataclass(frozen=True, kw_only=True)
class ForwardingChallenge:
    token: str
    campaign_key: str


@dataclass(frozen=True, kw_only=True)
class _ForwardingChallengePayload:
    team_id: int
    channel_id: UUID
    setup_id: UUID


class ForwardingChallengeResult(StrEnum):
    NOT_CHALLENGE = "not_challenge"
    CONSUMED = "consumed"
    ACTIVATED = "activated"


def create_forwarding_challenge(*, team_id: int, channel_id: UUID, setup_id: UUID) -> ForwardingChallenge:
    token = signing.dumps(
        {
            "purpose": _FORWARDING_CHALLENGE_PURPOSE,
            "team_id": team_id,
            "channel_id": str(channel_id),
            "setup_id": str(setup_id),
            "nonce": secrets.token_urlsafe(16),
        },
        salt=_FORWARDING_CHALLENGE_SALT,
        compress=True,
    )
    token_hash = sha256(token.encode()).hexdigest()[:16]
    return ForwardingChallenge(
        token=token,
        campaign_key=f"customer-email-forwarding:{setup_id}:{token_hash}",
    )


def _load_forwarding_challenge(token: str) -> tuple[_ForwardingChallengePayload | None, bool]:
    expired = False
    try:
        raw_payload = signing.loads(
            token,
            salt=_FORWARDING_CHALLENGE_SALT,
            max_age=FORWARDING_CHALLENGE_MAX_AGE_SECONDS,
        )
    except signing.SignatureExpired:
        expired = True
        try:
            raw_payload = signing.loads(token, salt=_FORWARDING_CHALLENGE_SALT)
        except signing.BadSignature:
            return None, False
    except signing.BadSignature:
        return None, False

    if not isinstance(raw_payload, dict):
        return None, False
    purpose = raw_payload.get("purpose")
    team_id = raw_payload.get("team_id")
    channel_id = raw_payload.get("channel_id")
    setup_id = raw_payload.get("setup_id")
    nonce = raw_payload.get("nonce")
    if (
        purpose != _FORWARDING_CHALLENGE_PURPOSE
        or not isinstance(team_id, int)
        or isinstance(team_id, bool)
        or not isinstance(channel_id, str)
        or not isinstance(setup_id, str)
        or not isinstance(nonce, str)
        or not nonce
    ):
        return None, False
    try:
        parsed_channel_id = UUID(channel_id)
        parsed_setup_id = UUID(setup_id)
    except ValueError:
        return None, False
    return (
        _ForwardingChallengePayload(
            team_id=team_id,
            channel_id=parsed_channel_id,
            setup_id=parsed_setup_id,
        ),
        expired,
    )


def process_forwarding_challenges(
    *,
    team_id: int,
    channel: EmailChannel,
    capture_address: str,
    challenge_tokens: tuple[str, ...],
) -> ForwardingChallengeResult:
    saw_bound_challenge = False
    expected_capture_prefix = f"team-{channel.inbound_token}@"

    for token in challenge_tokens:
        payload, expired = _load_forwarding_challenge(token)
        if payload is None:
            continue
        if (
            payload.team_id != team_id
            or payload.channel_id != channel.id
            or not capture_address.startswith(expected_capture_prefix)
        ):
            continue
        saw_bound_challenge = True
        if expired:
            continue

        with transaction.atomic():
            locked_channel = (
                EmailChannel.objects.select_for_update()
                .filter(
                    id=channel.id,
                    team_id=team_id,
                    kind=EmailChannelKind.CUSTOMER_COMMUNICATION,
                )
                .first()
            )
            if locked_channel is None:
                return ForwardingChallengeResult.CONSUMED
            if locked_channel.connection_status == EmailChannelConnectionStatus.ACTIVE:
                return ForwardingChallengeResult.CONSUMED
            if locked_channel.connection_status != EmailChannelConnectionStatus.PENDING_CONFIRMATION:
                return ForwardingChallengeResult.CONSUMED

            setup = (
                EmailChannelSetup.objects.for_team(team_id)
                .select_for_update()
                .filter(
                    id=payload.setup_id,
                    channel_id=locked_channel.id,
                    provider=EmailChannelSetupProvider.GOOGLE,
                )
                .first()
            )
            if setup is None:
                continue

            now = timezone.now()
            if setup.expires_at <= now:
                setup.delete()
                locked_channel.connection_status = EmailChannelConnectionStatus.CONFIRMATION_EXPIRED
                locked_channel.save(update_fields=["connection_status"])
                return ForwardingChallengeResult.CONSUMED

            setup.delete()
            locked_channel.connection_status = EmailChannelConnectionStatus.ACTIVE
            locked_channel.save(update_fields=["connection_status"])
            return ForwardingChallengeResult.ACTIVATED

    return ForwardingChallengeResult.CONSUMED if saw_bound_challenge else ForwardingChallengeResult.NOT_CHALLENGE


def _google_source_email(email: ParsedEmail) -> str | None:
    match = _GOOGLE_FORWARDING_SUBJECT_RE.fullmatch(email.subject.strip())
    if match is None:
        return None
    return match.group("source").lower()


def _validated_google_action(email: ParsedEmail) -> str | None:
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


def _is_google_authenticated(email: ParsedEmail) -> bool:
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
    email: ParsedEmail,
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
