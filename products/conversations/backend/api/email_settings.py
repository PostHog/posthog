"""Email channel settings API for connect/disconnect flows."""

import uuid
import secrets
from email.utils import formataddr, make_msgid

from django.core import mail
from django.db import IntegrityError, transaction

import structlog
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.instance_setting import get_instance_setting
from posthog.models.team import Team
from posthog.models.user import User
from posthog.rate_limit import EmailSendTestThrottle, EmailVerifyDomainThrottle

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
from products.conversations.backend.models import EmailChannel
from products.conversations.backend.models.team_conversations_email_config import MAX_EMAIL_CONFIGS_PER_TEAM
from products.conversations.backend.permissions import IsConversationsAdmin

logger = structlog.get_logger(__name__)


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


def _config_to_dict(config: EmailChannel, inbound_domain: str | None = None) -> dict:
    """Serialize a config to the API response shape."""
    forwarding_address = f"team-{config.inbound_token}@{inbound_domain}" if inbound_domain else None
    return {
        "id": config.id,
        "from_email": config.from_email,
        "from_name": config.from_name,
        "forwarding_address": forwarding_address,
        "domain": config.domain,
        "domain_verified": config.domain_verified,
        "dns_records": config.dns_records,
    }


def _release_domain_if_unused(team: Team, domain: str) -> None:
    """Best-effort removal of a Mailgun registration that no config ended up using.

    Left in place, the registration would make every future connect for this
    domain fail with a domain conflict.

    The `exists()` check narrows but cannot fully close a TOCTOU window: a
    concurrent connect could persist a config on this domain between the check and
    the delete. Mailgun calls run outside the team-row lock by design, so we accept
    that window; the loser at worst re-registers on its next verify.
    """
    if EmailChannel.objects.filter(domain=domain).exists():
        return
    try:
        mailgun_delete_domain(domain)
    except Exception:
        logger.exception("email_connect_release_domain_failed", team_id=team.id, domain=domain)


def _try_reclaim_stranded_domain(team: Team, domain: str) -> dict | None:
    """Recover a domain stranded in our Mailgun account with no config referencing it.

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
    if EmailChannel.objects.filter(domain=domain).exists():
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
    if EmailChannel.objects.filter(domain=domain).exists():
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


class EmailConnectSerializer(serializers.Serializer):
    from_email = serializers.EmailField()
    from_name = serializers.CharField(max_length=255)

    def validate_from_email(self, value: str) -> str:
        return value.lower()

    def validate_from_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Display name cannot be blank.")
        return value


class ConfigIdSerializer(serializers.Serializer):
    config_id = serializers.UUIDField()


class EmailStatusView(APIView):
    """Return all email configs for the current team."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, *args, **kwargs) -> Response:
        result = _get_team_from_request(request)
        if isinstance(result, Response):
            return result
        _, team = result

        configs = EmailChannel.objects.filter(team=team).order_by("created_at")
        inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN")

        return Response({"configs": [_config_to_dict(c, inbound_domain) for c in configs]})


class EmailConnectView(APIView):
    permission_classes = [IsAuthenticated, IsConversationsAdmin]

    def post(self, request: Request, *args, **kwargs) -> Response:
        result = _get_team_from_request(request)
        if isinstance(result, Response):
            return result
        user, team = result

        serializer = EmailConnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from_email: str = serializer.validated_data["from_email"]
        from_name: str = serializer.validated_data["from_name"]
        domain = from_email.split("@")[1]

        inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN")
        if not inbound_domain:
            return Response(
                {"error": "Email inbound domain not configured. Set CONVERSATIONS_EMAIL_INBOUND_DOMAIN."},
                status=400,
            )

        # Guard: cross-org domain ownership
        if EmailChannel.objects.filter(domain=domain).exclude(team__organization_id=team.organization_id).exists():
            return Response({"error": "This domain is already in use by another organization."}, status=409)

        # Check if org already has a config on this domain (reuse Mailgun registration + DNS records)
        sibling = EmailChannel.objects.filter(team__organization_id=team.organization_id, domain=domain).first()

        dns_records: dict = {}
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
                    logger.info("email_connect_mailgun_domain_conflict", team_id=team.id, domain=domain, error=str(e))
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

                current_count = EmailChannel.objects.filter(team=team).count()
                if current_count >= MAX_EMAIL_CONFIGS_PER_TEAM:
                    failure = Response(
                        {"error": f"Maximum of {MAX_EMAIL_CONFIGS_PER_TEAM} email addresses per team."},
                        status=400,
                    )
                else:
                    config = EmailChannel.objects.create(
                        team=team,
                        inbound_token=secrets.token_hex(16),
                        from_email=from_email,
                        from_name=from_name,
                        domain=domain,
                        dns_records=dns_records,
                        domain_verified=sibling.domain_verified if sibling else False,
                    )
                    _set_email_enabled(team, enabled=True)
        except IntegrityError:
            failure = Response({"error": "This email address is already connected."}, status=409)

        if config is None:
            # Failure responses are deferred to here so the Mailgun cleanup call
            # doesn't run inside the atomic block while the team row is locked.
            if not sibling:
                _release_domain_if_unused(team, domain)
            assert failure is not None
            return failure

        logger.info(
            "email_channel_connected",
            team_id=team.id,
            domain=domain,
            from_email=from_email,
            config_id=config.id,
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

    def post(self, request: Request, *args, **kwargs) -> Response:
        result = _resolve_config_from_request(request)
        if isinstance(result, Response):
            return result
        user, team, config = result

        if not config.domain_verified:
            return Response({"error": "Domain not yet verified. Please verify DNS records first."}, status=400)

        inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN") or config.domain
        message_id = make_msgid(domain=inbound_domain)
        from_addr = formataddr((config.from_name, config.from_email))

        email_message = mail.EmailMultiAlternatives(
            subject="Test email from PostHog Conversations",
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
                {"error": "Conversations email not configured on this instance"},
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


class EmailDisconnectView(APIView):
    permission_classes = [IsAuthenticated, IsConversationsAdmin]

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
            config = EmailChannel.objects.select_for_update().filter(id=config_id, team=team).first()
            if not config:
                return Response({"error": "Email config not found"}, status=404)

            domain_to_delete = config.domain
            config.delete()

            # Only delete from Mailgun if no other config (on any team) uses this domain
            if not EmailChannel.objects.filter(domain=domain_to_delete).exists():
                should_delete_from_mailgun = True

            # Only disable email on team if this was the last config
            if not EmailChannel.objects.filter(team=team).exists():
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
