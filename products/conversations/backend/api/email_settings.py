"""Email channel settings API for connect/disconnect flows."""

import uuid
import secrets
from email.utils import formataddr, make_msgid
from hashlib import sha256

from django.core import exceptions, mail
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.dataclasses import frozen
from posthog.email import EmailMessage, is_smtp_email_service_available
from posthog.models.instance_setting import get_instance_setting
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.rate_limit import EmailForwardingChallengeThrottle, EmailSendTestThrottle, EmailVerifyDomainThrottle

from products.conversations.backend.mailgun import (
    MailgunDomainConflict,
    MailgunDomainNotRegistered,
    MailgunError,
    MailgunNotConfigured,
    add_domain as mailgun_add_domain,
    delete_domain as mailgun_delete_domain,
    get_domain as mailgun_get_domain,
    send_mime,
    verify_domain as mailgun_verify_domain,
)
from products.conversations.backend.models import (
    EmailChannel,
    EmailChannelConnectionStatus,
    EmailChannelKind,
    EmailChannelSetup,
    EmailChannelSetupProvider,
)
from products.conversations.backend.models.team_conversations_email_config import (
    MAX_CUSTOMER_COMMUNICATION_CHANNELS_PER_TEAM,
    MAX_EMAIL_CONFIGS_PER_TEAM,
    MAX_PENDING_CUSTOMER_COMMUNICATION_CHANNELS_PER_OWNER,
)
from products.conversations.backend.permissions import IsConversationsAdmin
from products.conversations.backend.services.email_channel_setup import (
    CUSTOMER_EMAIL_SETUP_TTL,
    FORWARDING_CHALLENGE_HEADER,
    create_forwarding_challenge,
)

logger = structlog.get_logger(__name__)

FORWARDING_CHALLENGE_BASE_COOLDOWN_SECONDS = 30
FORWARDING_CHALLENGE_MAX_COOLDOWN_SECONDS = 60 * 60
FORWARDING_CHALLENGE_MAX_SEND_ATTEMPTS = 8


@frozen
class ForwardingChallengeRateLimitKeys:
    cooldown: str
    attempts: str


def _forwarding_challenge_rate_limit_keys(recipient: str) -> ForwardingChallengeRateLimitKeys:
    recipient_hash = sha256(recipient.strip().lower().encode()).hexdigest()
    key_prefix = f"customer-email-forwarding-challenge:{recipient_hash}"
    return ForwardingChallengeRateLimitKeys(
        cooldown=f"{key_prefix}:cooldown",
        attempts=f"{key_prefix}:attempts",
    )


def _forwarding_challenge_cooldown_seconds(attempt_count: int) -> int:
    return min(
        FORWARDING_CHALLENGE_BASE_COOLDOWN_SECONDS * (2**attempt_count),
        FORWARDING_CHALLENGE_MAX_COOLDOWN_SECONDS,
    )


def _get_team_from_request(request: Request) -> tuple[User, Team] | Response:
    """Extract authenticated user + team from request. Returns Response on failure."""
    user = request.user
    if not isinstance(user, User) or user.current_team is None:
        return Response({"error": "No current team selected"}, status=400)
    return user, user.current_team


def _set_email_enabled(team: Team, *, enabled: bool) -> None:
    """Atomically set email_enabled on the team. Must run inside transaction.atomic()."""
    t = Team.objects.select_for_update().get(id=team.id)
    s = t.conversations_settings or {}
    s["email_enabled"] = enabled
    t.conversations_settings = s
    t.save(update_fields=["conversations_settings"])


def _get_config_for_team(config_id: uuid.UUID, team: Team) -> EmailChannel | None:
    """Look up a config by id scoped to team. Returns None if not found."""
    return EmailChannel.objects.filter(id=config_id, team=team).first()


def _is_organization_admin(user: User, team: Team) -> bool:
    return OrganizationMembership.objects.filter(
        organization_id=team.organization_id,
        user=user,
        level__gte=OrganizationMembership.Level.ADMIN,
    ).exists()


def _resolve_config_from_request(request: Request) -> tuple[User, Team, EmailChannel] | Response:
    """Parse config_id from request body, look up config scoped to team.

    Returns (user, team, config) or a Response on failure.
    """
    result = _get_team_from_request(request)
    if isinstance(result, Response):
        return result
    user, team = result

    id_serializer = ConfigIdSerializer(data=request.data)
    id_serializer.is_valid(raise_exception=True)
    config = _get_config_for_team(id_serializer.validated_data["config_id"], team)
    if not config:
        return Response({"error": "Email config not found"}, status=404)

    return user, team, config


def _config_to_dict(config: EmailChannel, inbound_domain: str | None = None) -> dict[str, object]:
    forwarding_address = f"team-{config.inbound_token}@{inbound_domain}" if inbound_domain else None
    setup: EmailChannelSetup | None
    try:
        setup = config.setup
    except EmailChannelSetup.DoesNotExist:
        setup = None
    return {
        "id": config.id,
        "kind": config.kind,
        "owner_id": config.owner_id,
        "from_email": config.from_email,
        "from_name": config.from_name,
        "forwarding_address": forwarding_address,
        "domain": config.domain,
        "domain_verified": config.domain_verified,
        "dns_records": config.dns_records,
        "is_default": config.is_default,
        "connection_status": config.connection_status,
        "setup_expires_at": setup.expires_at if setup is not None else None,
        "confirmation_available": bool(setup and setup.confirmation_action),
    }


def _expire_customer_email_setups(*, team: Team, owner: User) -> None:
    now = timezone.now()
    expired_channel_ids = list(
        EmailChannelSetup.objects.for_team(team.id)
        .filter(channel__owner=owner, expires_at__lte=now)
        .values_list("channel_id", flat=True)
    )
    if not expired_channel_ids:
        return
    with transaction.atomic():
        EmailChannelSetup.objects.for_team(team.id).filter(
            channel_id__in=expired_channel_ids,
            expires_at__lte=now,
        ).delete()
        EmailChannel.objects.filter(
            team=team,
            owner=owner,
            id__in=expired_channel_ids,
            connection_status=EmailChannelConnectionStatus.PENDING_CONFIRMATION,
        ).update(connection_status=EmailChannelConnectionStatus.CONFIRMATION_EXPIRED)


def _release_expired_customer_email_reservation(*, from_email: str) -> None:
    channel = (
        EmailChannel.objects.select_for_update()
        .filter(
            from_email=from_email,
            kind=EmailChannelKind.CUSTOMER_COMMUNICATION,
        )
        .first()
    )
    if channel is None or channel.connection_status == EmailChannelConnectionStatus.ACTIVE:
        return

    setup = EmailChannelSetup.objects.for_team(channel.team_id).filter(channel=channel).first()

    setup_expired = setup is None or setup.expires_at <= timezone.now()
    if channel.connection_status == EmailChannelConnectionStatus.CONFIRMATION_EXPIRED or setup_expired:
        channel.delete()


def _release_domain_if_unused(team: Team, domain: str) -> None:
    """Best-effort removal of a Mailgun registration that no support config uses.

    Customer communication channels only receive captured mail, so they do not
    own Mailgun sending-domain registrations. The support connect that loses a
    concurrent race can re-register on its next verify.
    """
    if EmailChannel.objects.filter(domain=domain, kind=EmailChannelKind.SUPPORT).exists():
        return
    try:
        mailgun_delete_domain(domain)
    except Exception:
        logger.exception("email_connect_release_domain_failed", team_id=team.id, domain=domain)


def _try_reclaim_stranded_domain(team: Team, domain: str) -> dict | None:
    """Recover a domain stranded in our Mailgun account with no support config referencing it.

    A connect that registered the domain but failed to persist a config, or a
    disconnect whose Mailgun delete failed, leaves such a registration behind —
    and every reconnect then fails with a domain conflict. Reclaiming is only
    safe while Mailgun cannot verify the domain: in that state it cannot send,
    and re-registering issues fresh DNS records, so whoever reclaims it still
    has to prove DNS control. Verified (or disabled) domains are left for
    operators to reconcile.

    Returns fresh DNS records when the domain was reclaimed, None when the
    conflict stands.
    """
    if EmailChannel.objects.filter(domain=domain, kind=EmailChannelKind.SUPPORT).exists():
        return None

    # Decision phase (reads only). A lookup/verify failure here must leave the
    # original conflict standing, not delete anything.
    try:
        mg_domain = mailgun_get_domain(domain)
        if mg_domain is None:
            # Not in our account — the domain is claimed by another Mailgun account.
            return None

        state = mg_domain.get("state")
        if state != "unverified":
            # A stranded domain can sit "active" long after its DNS records were
            # removed — re-verify before treating it as genuinely in use.
            state = mailgun_verify_domain(domain).get("state")
    except Exception:
        logger.exception("email_connect_reclaim_lookup_failed", team_id=team.id, domain=domain)
        return None

    if state != "unverified":
        return None

    # Re-check immediately before the destructive delete. A concurrent connect for the
    # same brand-new domain may have registered it and be persisting a config since our
    # first check (Mailgun calls run outside the team-row lock by design). This narrows
    # — does not close — that window, but the read-only decision phase above is where
    # most of the latency sits, so the remaining window is small.
    if EmailChannel.objects.filter(domain=domain, kind=EmailChannelKind.SUPPORT).exists():
        return None

    # Mutation phase. If the delete lands but the re-add fails, the stale registration
    # is already gone, so the next connect registers the now-absent domain cleanly. Emit
    # a distinct signal so that half-completed state is diagnosable.
    try:
        mailgun_delete_domain(domain)
        dns_records = mailgun_add_domain(domain)
    except Exception:
        logger.exception("email_connect_reclaim_rewrite_failed", team_id=team.id, domain=domain)
        return None

    logger.info("email_connect_reclaimed_stranded_domain", team_id=team.id, domain=domain)
    return dns_records


class EmailChannelKindQuerySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=EmailChannelKind.choices,
        default=EmailChannelKind.SUPPORT,
        required=False,
        help_text="Email channel kind to return. Defaults to support channels.",
    )


class EmailConnectSerializer(serializers.Serializer):
    from_email = serializers.EmailField(help_text="Email address that receives forwarded mail and sends replies.")
    from_name = serializers.CharField(max_length=255, help_text="Display name used for outbound email.")
    kind = serializers.ChoiceField(
        choices=EmailChannelKind.choices,
        default=EmailChannelKind.SUPPORT,
        required=False,
        help_text="Whether the address handles support or customer communication.",
    )
    owner_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Organization member who owns a customer communication channel. Must be omitted for support.",
    )

    def validate_from_email(self, value: str) -> str:
        return value.lower()

    def validate_from_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Display name cannot be blank.")
        return value

    def validate(self, attrs: dict) -> dict:
        kind = attrs.get("kind", EmailChannelKind.SUPPORT)
        owner_id = attrs.get("owner_id")
        if kind == EmailChannelKind.CUSTOMER_COMMUNICATION and owner_id is None:
            raise serializers.ValidationError({"owner_id": "Owner is required for customer communication channels."})
        if kind == EmailChannelKind.SUPPORT and owner_id is not None:
            raise serializers.ValidationError({"owner_id": "Support channels cannot have an owner."})
        return attrs


class ConfigIdSerializer(serializers.Serializer):
    config_id = serializers.UUIDField(help_text="Email channel ID.")


class EmailDnsRecordSerializer(serializers.Serializer):
    record_type = serializers.CharField(required=False, allow_blank=True, help_text="DNS record type.")
    name = serializers.CharField(required=False, allow_blank=True, help_text="DNS record hostname.")
    value = serializers.CharField(required=False, allow_blank=True, help_text="DNS record value.")
    valid = serializers.CharField(required=False, allow_blank=True, help_text="Mailgun verification status.")


class EmailDnsRecordsSerializer(serializers.Serializer):
    sending_dns_records = EmailDnsRecordSerializer(
        many=True,
        required=False,
        help_text="DNS records required for outbound sending.",
    )


class EmailChannelConfigSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Email channel ID.")
    kind = serializers.ChoiceField(
        choices=EmailChannelKind.choices,
        read_only=True,
        help_text="Whether the channel handles support or customer communication.",
    )
    owner_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="User who owns a customer communication channel, or null for support.",
    )
    from_email = serializers.EmailField(read_only=True, help_text="Sender and forwarding source email address.")
    from_name = serializers.CharField(read_only=True, help_text="Outbound sender display name.")
    forwarding_address = serializers.EmailField(
        read_only=True,
        allow_null=True,
        help_text="PostHog address to configure as a forwarding destination.",
    )
    domain = serializers.CharField(read_only=True, help_text="Sending domain registered with Mailgun.")
    domain_verified = serializers.BooleanField(read_only=True, help_text="Whether Mailgun verified the domain.")
    dns_records = EmailDnsRecordsSerializer(
        read_only=True,
        allow_null=True,
        help_text="DNS records required to verify the sending domain.",
    )
    is_default = serializers.BooleanField(
        read_only=True,
        help_text="Whether this support channel is the team's fallback sender.",
    )
    connection_status = serializers.ChoiceField(
        choices=EmailChannelConnectionStatus.choices,
        read_only=True,
        help_text="Whether forwarding setup is pending, active, or expired.",
    )
    setup_expires_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the pending forwarding setup expires.",
    )
    confirmation_available = serializers.BooleanField(
        read_only=True,
        help_text="Whether an authenticated forwarding confirmation is ready for the owner.",
    )


class EmailStatusResponseSerializer(serializers.Serializer):
    configs = EmailChannelConfigSerializer(many=True, read_only=True, help_text="Connected email channels.")


class EmailConnectResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField(read_only=True, help_text="Whether the channel was connected.")
    config = EmailChannelConfigSerializer(read_only=True, help_text="Connected email channel.")


class EmailChannelErrorSerializer(serializers.Serializer):
    error = serializers.CharField(read_only=True, help_text="Reason the request failed.")


class EmailChannelOperationResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField(read_only=True, help_text="Whether the operation succeeded.")


class EmailConfirmForwardingResponseSerializer(EmailChannelOperationResponseSerializer):
    confirmation_url = serializers.URLField(
        read_only=True,
        help_text="Authenticated Google forwarding confirmation URL. Opening it does not verify forwarding to PostHog.",
    )


class EmailSendTestResponseSerializer(EmailChannelOperationResponseSerializer):
    sent_to = serializers.EmailField(read_only=True, help_text="Address that received the test email.")


class EmailStatusView(APIView):
    """Return connected email channels for the current team."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["conversations"],
        parameters=[EmailChannelKindQuerySerializer],
        responses={
            200: EmailStatusResponseSerializer,
            400: OpenApiResponse(response=EmailChannelErrorSerializer),
        },
    )
    def get(self, request: Request, *args, **kwargs) -> Response:
        result = _get_team_from_request(request)
        if isinstance(result, Response):
            return result
        user, team = result

        query_serializer = EmailChannelKindQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        kind = query_serializer.validated_data["kind"]
        configs = EmailChannel.objects.filter(team=team, kind=kind)
        if kind == EmailChannelKind.CUSTOMER_COMMUNICATION:
            _expire_customer_email_setups(team=team, owner=user)
            configs = configs.filter(owner=user)
        configs = configs.select_related("setup").order_by("created_at")
        inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN")

        return Response({"configs": [_config_to_dict(c, inbound_domain) for c in configs]})


class EmailConnectView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["conversations"],
        request=EmailConnectSerializer,
        responses={
            200: EmailConnectResponseSerializer,
            400: OpenApiResponse(response=EmailChannelErrorSerializer),
            403: OpenApiResponse(response=EmailChannelErrorSerializer),
            409: OpenApiResponse(response=EmailChannelErrorSerializer),
            502: OpenApiResponse(response=EmailChannelErrorSerializer),
        },
    )
    def post(self, request: Request, *args, **kwargs) -> Response:
        result = _get_team_from_request(request)
        if isinstance(result, Response):
            return result
        user, team = result

        serializer = EmailConnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from_email: str = serializer.validated_data["from_email"]
        from_name: str = serializer.validated_data["from_name"]
        kind: str = serializer.validated_data["kind"]
        owner: User | None = None
        is_admin = _is_organization_admin(user, team)
        if kind == EmailChannelKind.SUPPORT:
            if not is_admin:
                return Response({"error": "Only organization admins can manage support email channels."}, status=403)
        else:
            membership = (
                OrganizationMembership.objects.filter(
                    organization_id=team.organization_id,
                    user_id=serializer.validated_data["owner_id"],
                    user__is_active=True,
                )
                .select_related("user")
                .first()
            )
            if membership is None:
                return Response({"error": "Owner must be an active member of this organization."}, status=400)
            owner = membership.user
            if owner.id != user.id and not is_admin:
                return Response({"error": "You can only connect your own email address."}, status=403)

        domain = from_email.split("@")[1]
        inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN")
        if not inbound_domain:
            return Response(
                {"error": "Email inbound domain not configured. Set CONVERSATIONS_EMAIL_INBOUND_DOMAIN."},
                status=400,
            )

        sibling: EmailChannel | None = None
        dns_records: dict = {}
        if kind == EmailChannelKind.SUPPORT:
            if (
                EmailChannel.objects.filter(domain=domain, kind=EmailChannelKind.SUPPORT)
                .exclude(team__organization_id=team.organization_id)
                .exists()
            ):
                return Response({"error": "This domain is already in use by another organization."}, status=409)

            sibling = (
                EmailChannel.objects.filter(
                    team__organization_id=team.organization_id,
                    domain=domain,
                    kind=EmailChannelKind.SUPPORT,
                )
                .order_by("-domain_verified", "created_at")
                .first()
            )
            if sibling:
                dns_records = sibling.dns_records
            else:
                try:
                    dns_records = mailgun_add_domain(domain)
                except MailgunNotConfigured:
                    logger.info("email_connect_mailgun_not_configured", team_id=team.id, domain=domain)
                    return Response({"error": "Mailgun API key not configured"}, status=400)
                except MailgunDomainConflict as e:
                    reclaimed = _try_reclaim_stranded_domain(team, domain)
                    if reclaimed is None:
                        logger.info(
                            "email_connect_mailgun_domain_conflict", team_id=team.id, domain=domain, error=str(e)
                        )
                        return Response(
                            {
                                "error": "This domain cannot be registered for sending. "
                                "It may already be claimed by another account."
                            },
                            status=400,
                        )
                    dns_records = reclaimed
                except Exception:
                    logger.exception("email_connect_mailgun_add_domain_failed", team_id=team.id, domain=domain)
                    return Response(
                        {"error": "Failed to register domain for sending. Please try again later."},
                        status=502,
                    )

        config: EmailChannel | None = None
        failure: Response | None = None
        try:
            with transaction.atomic():
                # Lock team row to serialize concurrent connects and enforce the config limit
                Team.objects.select_for_update().get(id=team.id)

                if kind == EmailChannelKind.CUSTOMER_COMMUNICATION:
                    _release_expired_customer_email_reservation(from_email=from_email)

                channels = EmailChannel.objects.filter(team=team, kind=kind)
                if kind == EmailChannelKind.CUSTOMER_COMMUNICATION:
                    current_count = channels.exclude(
                        connection_status=EmailChannelConnectionStatus.CONFIRMATION_EXPIRED
                    ).count()
                    pending_owner_count = channels.filter(
                        owner=owner,
                        connection_status=EmailChannelConnectionStatus.PENDING_CONFIRMATION,
                    ).count()
                else:
                    current_count = channels.count()
                    pending_owner_count = 0

                max_channels = (
                    MAX_EMAIL_CONFIGS_PER_TEAM
                    if kind == EmailChannelKind.SUPPORT
                    else MAX_CUSTOMER_COMMUNICATION_CHANNELS_PER_TEAM
                )
                if pending_owner_count >= MAX_PENDING_CUSTOMER_COMMUNICATION_CHANNELS_PER_OWNER:
                    failure = Response(
                        {
                            "error": f"You can have up to {MAX_PENDING_CUSTOMER_COMMUNICATION_CHANNELS_PER_OWNER} "
                            "email addresses awaiting confirmation. Finish or disconnect one before adding another."
                        },
                        status=400,
                    )
                elif current_count >= max_channels:
                    channel_name = "support" if kind == EmailChannelKind.SUPPORT else "customer communication"
                    failure = Response(
                        {"error": f"Maximum of {max_channels} {channel_name} email addresses per team."},
                        status=400,
                    )
                else:
                    config = EmailChannel.objects.create(
                        team=team,
                        kind=kind,
                        owner=owner,
                        inbound_token=secrets.token_hex(16),
                        from_email=from_email,
                        from_name=from_name,
                        domain=domain,
                        dns_records=dns_records,
                        domain_verified=sibling.domain_verified if sibling else False,
                        is_default=kind == EmailChannelKind.SUPPORT and current_count == 0,
                        connection_status=(
                            EmailChannelConnectionStatus.ACTIVE
                            if kind == EmailChannelKind.SUPPORT
                            else EmailChannelConnectionStatus.PENDING_CONFIRMATION
                        ),
                    )
                    if kind == EmailChannelKind.SUPPORT:
                        _set_email_enabled(team, enabled=True)
                    else:
                        EmailChannelSetup.objects.for_team(team.id).create(
                            team=team,
                            channel=config,
                            provider=EmailChannelSetupProvider.GOOGLE,
                            expires_at=timezone.now() + CUSTOMER_EMAIL_SETUP_TTL,
                        )
        except IntegrityError:
            failure = Response({"error": "This email address is already connected."}, status=409)

        if config is None:
            # Failure responses are deferred to here so the Mailgun cleanup call
            # doesn't run inside the atomic block while the team row is locked.
            if kind == EmailChannelKind.SUPPORT and not sibling:
                _release_domain_if_unused(team, domain)
            assert failure is not None
            return failure

        logger.info(
            "email_channel_connected",
            team_id=team.id,
            domain=domain,
            from_email=from_email,
            config_id=config.id,
            kind=config.kind,
            owner_id=config.owner_id,
            user_id=user.id,
        )

        return Response({"ok": True, "config": _config_to_dict(config, inbound_domain)})


class EmailVerifyDomainView(APIView):
    """Trigger Mailgun DNS verification and update local config."""

    permission_classes = [IsAuthenticated, IsConversationsAdmin]
    throttle_classes = [EmailVerifyDomainThrottle]

    def post(self, request: Request, *args, **kwargs) -> Response:
        result = _resolve_config_from_request(request)
        if isinstance(result, Response):
            return result
        user, team, config = result

        try:
            mg_result = mailgun_verify_domain(config.domain)
        except MailgunNotConfigured:
            return Response({"error": "Mailgun API key not configured"}, status=400)
        except Exception:
            logger.exception("email_verify_domain_failed", team_id=team.id, domain=config.domain)
            return Response({"error": "Failed to verify domain with Mailgun"}, status=502)

        is_active = mg_result.get("state") == "active"
        dns_records = {"sending_dns_records": mg_result.get("sending_dns_records", [])}

        # Update all configs in this org sharing the same domain
        EmailChannel.objects.filter(team__organization_id=team.organization_id, domain=config.domain).update(
            domain_verified=is_active,
            dns_records=dns_records,
        )

        logger.info(
            "email_domain_verified",
            team_id=team.id,
            domain=config.domain,
            verified=is_active,
            config_id=config.id,
            user_id=user.id,
        )

        return Response({"domain_verified": is_active, "dns_records": dns_records})


class EmailSendTestView(APIView):
    """Send a test email to verify the outbound pipeline works."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [EmailSendTestThrottle]

    @extend_schema(
        request=ConfigIdSerializer,
        responses={
            200: EmailSendTestResponseSerializer,
            400: OpenApiResponse(response=EmailChannelErrorSerializer),
            404: OpenApiResponse(response=EmailChannelErrorSerializer),
            500: OpenApiResponse(response=EmailChannelErrorSerializer),
            502: OpenApiResponse(response=EmailChannelErrorSerializer),
        },
    )
    def post(self, request: Request, *args, **kwargs) -> Response:
        result = _resolve_config_from_request(request)
        if isinstance(result, Response):
            return result
        user, team, config = result

        if (
            config.kind == EmailChannelKind.CUSTOMER_COMMUNICATION
            and config.owner_id != user.id
            and not _is_organization_admin(user, team)
        ):
            return Response({"error": "Email config not found"}, status=404)
        if not config.domain_verified:
            return Response({"error": "Domain not yet verified. Please verify DNS records first."}, status=400)

        inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN") or config.domain
        message_id = make_msgid(domain=inbound_domain)
        from_addr = formataddr((config.from_name, config.from_email))

        email_message = mail.EmailMultiAlternatives(
            subject="Test email from PostHog Support",
            body="This is a test email to confirm your outbound email is working correctly.",
            from_email=from_addr,
            to=[user.email],
            headers={"Message-ID": message_id},
        )
        html_body = (
            "<p>This is a test email to confirm your outbound email is working correctly.</p>"
            "<p>If you received this, your email channel is configured properly.</p>"
        )
        email_message.attach_alternative(html_body, "text/html")

        mime_bytes = email_message.message().as_bytes(linesep="\r\n")

        try:
            send_mime(config.domain, mime_bytes, recipients=[user.email])
        except MailgunNotConfigured:
            logger.exception("email_send_test_not_configured", team_id=team.id, config_id=config.id)
            return Response(
                {"error": "Support email not configured on this instance"},
                status=500,
            )
        except MailgunDomainNotRegistered:
            logger.exception(
                "email_send_test_domain_not_registered",
                team_id=team.id,
                config_id=config.id,
                domain=config.domain,
            )
            config.mark_domain_unverified()
            return Response(
                {"error": "Domain not registered with Mailgun. Please reconnect."},
                status=502,
            )
        except MailgunError:
            logger.exception("email_send_test_failed", team_id=team.id, config_id=config.id)
            return Response({"error": "Failed to send test email"}, status=502)

        logger.info("email_test_sent", team_id=team.id, to=user.email, config_id=config.id, user_id=user.id)

        return Response({"ok": True, "sent_to": user.email})


class EmailSetDefaultView(APIView):
    """Make a support channel the team's default send-from identity."""

    permission_classes = [IsAuthenticated, IsConversationsAdmin]

    @extend_schema(
        request=ConfigIdSerializer,
        responses={
            200: EmailChannelOperationResponseSerializer,
            400: OpenApiResponse(response=EmailChannelErrorSerializer),
            404: OpenApiResponse(response=EmailChannelErrorSerializer),
        },
    )
    def post(self, request: Request, *args, **kwargs) -> Response:
        result = _get_team_from_request(request)
        if isinstance(result, Response):
            return result
        user, team = result

        id_serializer = ConfigIdSerializer(data=request.data)
        id_serializer.is_valid(raise_exception=True)
        config_id = id_serializer.validated_data["config_id"]

        with transaction.atomic():
            # Serialize all per-team default changes on the team row (the connect path takes the
            # same lock), so concurrent connect/set-default/disconnect can't race two is_default=True
            # rows into the partial unique constraint
            Team.objects.select_for_update().get(id=team.id)
            config = EmailChannel.objects.filter(id=config_id, team=team).first()
            if not config:
                return Response({"error": "Email config not found"}, status=404)
            if config.kind != EmailChannelKind.SUPPORT:
                return Response({"error": "Only support email channels can be primary."}, status=400)

            # Clear the current default first so the partial unique constraint is never violated.
            EmailChannel.objects.filter(
                team=team,
                kind=EmailChannelKind.SUPPORT,
                is_default=True,
            ).exclude(id=config.id).update(is_default=False)
            if not config.is_default:
                config.is_default = True
                config.save(update_fields=["is_default"])

        logger.info("email_channel_set_default", team_id=team.id, config_id=config_id, user_id=user.id)
        return Response({"ok": True})


class EmailVerifyForwardingView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [EmailForwardingChallengeThrottle]

    @extend_schema(
        tags=["conversations"],
        request=ConfigIdSerializer,
        responses={
            200: EmailChannelOperationResponseSerializer,
            400: OpenApiResponse(response=EmailChannelErrorSerializer),
            404: OpenApiResponse(response=EmailChannelErrorSerializer),
            429: OpenApiResponse(response=EmailChannelErrorSerializer),
            502: OpenApiResponse(response=EmailChannelErrorSerializer),
            503: OpenApiResponse(response=EmailChannelErrorSerializer),
        },
    )
    def post(self, request: Request, *args, **kwargs) -> Response:
        result = _get_team_from_request(request)
        if isinstance(result, Response):
            return result
        user, team = result

        id_serializer = ConfigIdSerializer(data=request.data)
        id_serializer.is_valid(raise_exception=True)
        config_id = id_serializer.validated_data["config_id"]

        with transaction.atomic():
            config = (
                EmailChannel.objects.select_for_update()
                .filter(
                    id=config_id,
                    team=team,
                    kind=EmailChannelKind.CUSTOMER_COMMUNICATION,
                    owner=user,
                )
                .first()
            )
            if config is None:
                return Response({"error": "Email config not found"}, status=404)
            if config.connection_status != EmailChannelConnectionStatus.PENDING_CONFIRMATION:
                return Response({"error": "This forwarding setup is not pending confirmation."}, status=400)

            setup = EmailChannelSetup.objects.for_team(team.id).select_for_update().filter(channel=config).first()
            if setup is None:
                return Response({"error": "This forwarding setup is no longer available."}, status=400)
            if setup.expires_at <= timezone.now():
                setup.delete()
                config.connection_status = EmailChannelConnectionStatus.CONFIRMATION_EXPIRED
                config.save(update_fields=["connection_status"])
                return Response({"error": "This forwarding setup expired. Add the email again to restart."}, status=400)

            setup_id = setup.id
            channel_id = config.id
            recipient = config.from_email

        if not is_smtp_email_service_available():
            return Response(
                {"error": "Email verification is not configured on this PostHog instance."},
                status=503,
            )

        rate_limit_keys = _forwarding_challenge_rate_limit_keys(recipient)
        cached_attempt_count = cache.get(rate_limit_keys.attempts, 0)
        attempt_count = (
            cached_attempt_count
            if isinstance(cached_attempt_count, int)
            and not isinstance(cached_attempt_count, bool)
            and cached_attempt_count >= 0
            else 0
        )
        if attempt_count >= FORWARDING_CHALLENGE_MAX_SEND_ATTEMPTS:
            return Response(
                {"error": "This email has reached the verification limit. Wait 24 hours before trying again."},
                status=429,
            )
        cooldown_seconds = _forwarding_challenge_cooldown_seconds(attempt_count)
        if not cache.add(rate_limit_keys.cooldown, True, timeout=cooldown_seconds):
            return Response(
                {"error": "A verification email was sent recently. Wait a moment and try again."},
                status=429,
            )

        challenge = create_forwarding_challenge(
            team_id=team.id,
            channel_id=channel_id,
            setup_id=setup_id,
        )
        try:
            message = EmailMessage(
                campaign_key=challenge.campaign_key,
                subject="Verify email forwarding to PostHog",
                template_name="customer_email_forwarding_verification",
                template_context={"forwarding_challenge": challenge.token},
                headers={FORWARDING_CHALLENGE_HEADER: challenge.token},
            )
            message.add_recipient(email=recipient)
            message.send()
        except exceptions.ImproperlyConfigured:
            cache.delete(rate_limit_keys.cooldown)
            return Response(
                {"error": "Email verification is not configured on this PostHog instance."},
                status=503,
            )
        except Exception:
            cache.delete(rate_limit_keys.cooldown)
            logger.error(  # noqa: TRY400 - exception details may contain the signed challenge token
                "customer_email_forwarding_challenge_enqueue_failed",
                team_id=team.id,
                config_id=str(channel_id),
            )
            return Response({"error": "Could not send the verification email. Try again."}, status=502)

        cache.set(
            rate_limit_keys.attempts,
            attempt_count + 1,
            timeout=int(CUSTOMER_EMAIL_SETUP_TTL.total_seconds()),
        )
        logger.info(
            "customer_email_forwarding_challenge_enqueued",
            team_id=team.id,
            config_id=str(channel_id),
            user_id=user.id,
        )
        return Response({"ok": True})


class EmailConfirmForwardingView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["conversations"],
        request=ConfigIdSerializer,
        responses={
            200: EmailConfirmForwardingResponseSerializer,
            400: OpenApiResponse(response=EmailChannelErrorSerializer),
            404: OpenApiResponse(response=EmailChannelErrorSerializer),
        },
    )
    def post(self, request: Request, *args, **kwargs) -> Response:
        result = _get_team_from_request(request)
        if isinstance(result, Response):
            return result
        user, team = result

        id_serializer = ConfigIdSerializer(data=request.data)
        id_serializer.is_valid(raise_exception=True)
        config_id = id_serializer.validated_data["config_id"]

        with transaction.atomic():
            config = (
                EmailChannel.objects.select_for_update()
                .filter(
                    id=config_id,
                    team=team,
                    kind=EmailChannelKind.CUSTOMER_COMMUNICATION,
                    owner=user,
                )
                .first()
            )
            if config is None:
                return Response({"error": "Email config not found"}, status=404)
            if config.connection_status != EmailChannelConnectionStatus.PENDING_CONFIRMATION:
                return Response({"error": "This forwarding setup is not pending confirmation."}, status=400)

            setup = EmailChannelSetup.objects.for_team(team.id).select_for_update().filter(channel=config).first()
            if setup is None:
                return Response({"error": "This forwarding setup is no longer available."}, status=400)
            if setup.expires_at <= timezone.now():
                setup.delete()
                config.connection_status = EmailChannelConnectionStatus.CONFIRMATION_EXPIRED
                config.save(update_fields=["connection_status"])
                return Response({"error": "This forwarding setup expired. Add the email again to restart."}, status=400)
            if not setup.confirmation_action:
                return Response({"error": "Gmail has not sent a forwarding confirmation yet."}, status=400)

            confirmation_url = setup.confirmation_action

        logger.info(
            "customer_email_forwarding_confirmation_opened",
            team_id=team.id,
            config_id=config.id,
            user_id=user.id,
        )
        return Response({"ok": True, "confirmation_url": confirmation_url})


class EmailDisconnectView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["conversations"],
        request=ConfigIdSerializer,
        responses={
            200: EmailChannelOperationResponseSerializer,
            403: OpenApiResponse(response=EmailChannelErrorSerializer),
            404: OpenApiResponse(response=EmailChannelErrorSerializer),
        },
    )
    def post(self, request: Request, *args, **kwargs) -> Response:
        result = _get_team_from_request(request)
        if isinstance(result, Response):
            return result
        user, team = result

        id_serializer = ConfigIdSerializer(data=request.data)
        id_serializer.is_valid(raise_exception=True)
        config_id = id_serializer.validated_data["config_id"]

        domain_to_delete: str | None = None
        should_delete_from_mailgun = False

        with transaction.atomic():
            # Same team-row lock as connect/set-default, so promoting a replacement default can't
            # race another default change into the partial unique constraint
            Team.objects.select_for_update().get(id=team.id)
            config = EmailChannel.objects.filter(id=config_id, team=team).first()
            is_admin = _is_organization_admin(user, team)
            if not config:
                return Response({"error": "Email config not found"}, status=404 if is_admin else 403)
            if config.kind == EmailChannelKind.SUPPORT and not is_admin:
                return Response({"error": "Only organization admins can manage support email channels."}, status=403)
            if config.kind == EmailChannelKind.CUSTOMER_COMMUNICATION and config.owner_id != user.id and not is_admin:
                return Response({"error": "Email config not found"}, status=404)

            domain_to_delete = config.domain
            was_default = config.is_default
            was_support_channel = config.kind == EmailChannelKind.SUPPORT
            config.delete()

            # Keep a support fallback sender after its previous default is removed.
            if was_default:
                replacement = (
                    EmailChannel.objects.filter(team=team, kind=EmailChannelKind.SUPPORT)
                    .order_by("-domain_verified", "created_at")
                    .first()
                )
                if replacement:
                    replacement.is_default = True
                    replacement.save(update_fields=["is_default"])

            # Only delete from Mailgun if no other config (on any team) uses this domain
            if (
                was_support_channel
                and not EmailChannel.objects.filter(
                    domain=domain_to_delete,
                    kind=EmailChannelKind.SUPPORT,
                ).exists()
            ):
                should_delete_from_mailgun = True

            # The legacy setting controls support email, not customer communication capture.
            if not EmailChannel.objects.filter(team=team, kind=EmailChannelKind.SUPPORT).exists():
                _set_email_enabled(team, enabled=False)

        if should_delete_from_mailgun:
            assert domain_to_delete is not None
            try:
                mailgun_delete_domain(domain_to_delete)
            except MailgunNotConfigured:
                logger.info("email_disconnect_no_mailgun_key", team_id=team.id)
            except Exception:
                logger.exception("email_disconnect_mailgun_delete_failed", team_id=team.id, domain=domain_to_delete)

        logger.info(
            "email_channel_disconnected",
            team_id=team.id,
            config_id=config_id,
            domain=domain_to_delete,
            user_id=user.id,
        )

        return Response({"ok": True})
