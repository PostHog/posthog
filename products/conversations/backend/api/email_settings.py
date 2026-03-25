"""Email channel settings API for connect/disconnect flows."""

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
    add_domain as mailgun_add_domain,
    delete_domain as mailgun_delete_domain,
    get_smtp_connection,
    verify_domain as mailgun_verify_domain,
)
from products.conversations.backend.models import TeamConversationsEmailConfig
from products.conversations.backend.permissions import IsConversationsAdmin

logger = structlog.get_logger(__name__)


def _enable_email_on_team(team: Team) -> None:
    """Atomically set email_enabled=True on the team's conversations_settings.

    Must be called inside a transaction.atomic() block.
    """
    t = Team.objects.select_for_update().get(id=team.id)
    s = t.conversations_settings or {}
    s["email_enabled"] = True
    t.conversations_settings = s
    t.save(update_fields=["conversations_settings"])


def _disable_email_on_team(team: Team) -> None:
    """Atomically set email_enabled=False on the team's conversations_settings.

    Must be called inside a transaction.atomic() block.
    """
    t = Team.objects.select_for_update().get(id=team.id)
    s = t.conversations_settings or {}
    s["email_enabled"] = False
    t.conversations_settings = s
    t.save(update_fields=["conversations_settings"])


class EmailConnectSerializer(serializers.Serializer):
    from_email = serializers.EmailField()
    from_name = serializers.CharField(max_length=255)

    def validate_from_email(self, value: str) -> str:
        return value.lower()


class EmailStatusView(APIView):
    """Return current email config status (forwarding address, connection state)."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        team = user.current_team
        settings_dict = team.conversations_settings or {}

        try:
            config = TeamConversationsEmailConfig.objects.get(team=team)
        except TeamConversationsEmailConfig.DoesNotExist:
            return Response({"connected": False})

        inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN")
        forwarding_address = f"team-{config.inbound_token}@{inbound_domain}" if inbound_domain else None

        return Response(
            {
                "connected": settings_dict.get("email_enabled", False),
                "forwarding_address": forwarding_address,
                "from_email": config.from_email,
                "from_name": config.from_name,
                "domain": config.domain,
                "domain_verified": config.domain_verified,
                "dns_records": config.dns_records,
            }
        )


class EmailConnectView(APIView):
    permission_classes = [IsAuthenticated, IsConversationsAdmin]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        serializer = EmailConnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        team = user.current_team
        from_email: str = serializer.validated_data["from_email"]
        from_name: str = serializer.validated_data["from_name"]
        domain = from_email.split("@")[1]

        inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN")
        if not inbound_domain:
            return Response(
                {"error": "Email inbound domain not configured. Set CONVERSATIONS_EMAIL_INBOUND_DOMAIN."},
                status=400,
            )

        # Register domain with Mailgun for outbound sending
        dns_records: dict = {}
        try:
            dns_records = mailgun_add_domain(domain)
        except ValueError as e:
            logger.info("email_connect_mailgun_domain_error", team_id=team.id, domain=domain, error=str(e))
            return Response(
                {
                    "error": "This domain cannot be registered for sending. It may already be claimed by another account."
                },
                status=400,
            )
        except Exception:
            logger.exception("email_connect_mailgun_add_domain_failed", team_id=team.id, domain=domain)
            return Response(
                {"error": "Failed to register domain for sending. Please try again later."},
                status=502,
            )

        try:
            config = self._upsert_config(team, from_email, from_name, domain, dns_records)
        except IntegrityError:
            # Domain unique constraint violation — another team owns this domain.
            # Do NOT call mailgun_delete_domain here: the domain belongs to the other team.
            return Response({"error": "This domain is already in use by another team."}, status=409)

        forwarding_address = f"team-{config.inbound_token}@{inbound_domain}"

        logger.info("email_channel_connected", team_id=team.id, domain=domain, user_id=user.id, user_email=user.email)

        return Response(
            {
                "ok": True,
                "forwarding_address": forwarding_address,
                "from_email": from_email,
                "from_name": from_name,
                "domain": domain,
                "dns_records": dns_records,
            }
        )

    @staticmethod
    def _upsert_config(
        team: Team,
        from_email: str,
        from_name: str,
        domain: str,
        dns_records: dict,
    ) -> TeamConversationsEmailConfig:
        """Create or update email config + enable email on team atomically.

        Raises IntegrityError if the domain unique constraint is violated
        (another team owns the domain).
        """
        try:
            with transaction.atomic():
                config = TeamConversationsEmailConfig.objects.select_for_update().get(team=team)
                config.from_email = from_email
                config.from_name = from_name
                config.domain = domain
                if dns_records:
                    config.dns_records = dns_records
                config.save(update_fields=["from_email", "from_name", "domain", "dns_records"])
                _enable_email_on_team(team)
                return config
        except TeamConversationsEmailConfig.DoesNotExist:
            pass

        try:
            with transaction.atomic():
                config = TeamConversationsEmailConfig.objects.create(
                    team=team,
                    inbound_token=secrets.token_hex(16),
                    from_email=from_email,
                    from_name=from_name,
                    domain=domain,
                    dns_records=dns_records,
                )
                _enable_email_on_team(team)
                return config
        except IntegrityError:
            # Could be team-level race (two concurrent creates) or domain conflict.
            # Distinguish: if the config now exists for this team, retry as update.
            if not TeamConversationsEmailConfig.objects.filter(team=team).exists():
                raise
            with transaction.atomic():
                config = TeamConversationsEmailConfig.objects.select_for_update().get(team=team)
                config.from_email = from_email
                config.from_name = from_name
                config.domain = domain
                if dns_records:
                    config.dns_records = dns_records
                config.save(update_fields=["from_email", "from_name", "domain", "dns_records"])
                _enable_email_on_team(team)
                return config


class EmailVerifyDomainView(APIView):
    """Trigger Mailgun DNS verification and update local config."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [EmailVerifyDomainThrottle]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        team = user.current_team

        try:
            config = TeamConversationsEmailConfig.objects.get(team=team)
        except TeamConversationsEmailConfig.DoesNotExist:
            return Response({"error": "Email channel not connected"}, status=400)

        try:
            result = mailgun_verify_domain(config.domain)
        except ValueError:
            return Response({"error": "Mailgun API key not configured"}, status=400)
        except Exception:
            logger.exception("email_verify_domain_failed", team_id=team.id, domain=config.domain)
            return Response({"error": "Failed to verify domain with Mailgun"}, status=502)

        is_active = result.get("state") == "active"
        config.domain_verified = is_active
        config.dns_records = {
            "sending_dns_records": result.get("sending_dns_records", []),
        }
        config.save(update_fields=["domain_verified", "dns_records"])

        logger.info(
            "email_domain_verified",
            team_id=team.id,
            domain=config.domain,
            verified=is_active,
            user_id=user.id,
        )

        return Response(
            {
                "domain_verified": is_active,
                "dns_records": config.dns_records,
            }
        )


class EmailSendTestView(APIView):
    """Send a test email to verify the outbound pipeline works."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [EmailSendTestThrottle]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        team = user.current_team

        try:
            config = TeamConversationsEmailConfig.objects.get(team=team)
        except TeamConversationsEmailConfig.DoesNotExist:
            return Response({"error": "Email channel not connected"}, status=400)

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

        connection = None
        try:
            connection = get_smtp_connection()
            connection.open()
            connection.send_messages([email_message])
        except Exception:
            logger.exception("email_send_test_failed", team_id=team.id)
            return Response({"error": "Failed to send test email. Check SMTP settings."}, status=502)
        finally:
            if connection:
                try:
                    connection.close()
                except Exception:
                    pass

        logger.info("email_test_sent", team_id=team.id, to=user.email, user_id=user.id)

        return Response({"ok": True, "sent_to": user.email})


class EmailDisconnectView(APIView):
    permission_classes = [IsAuthenticated, IsConversationsAdmin]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        team = user.current_team

        domain_to_delete: str | None = None
        should_delete_from_mailgun = False

        with transaction.atomic():
            try:
                config = TeamConversationsEmailConfig.objects.select_for_update().get(team=team)
                domain_to_delete = config.domain
                config.delete()
            except TeamConversationsEmailConfig.DoesNotExist:
                pass

            # Check while still holding the transaction so a concurrent connect can't sneak in
            if domain_to_delete and not TeamConversationsEmailConfig.objects.filter(domain=domain_to_delete).exists():
                should_delete_from_mailgun = True

            _disable_email_on_team(team)

        if should_delete_from_mailgun:
            assert domain_to_delete is not None
            try:
                mailgun_delete_domain(domain_to_delete)
            except ValueError:
                logger.info("email_disconnect_no_mailgun_key", team_id=team.id)
            except Exception:
                logger.exception("email_disconnect_mailgun_delete_failed", team_id=team.id, domain=domain_to_delete)

        logger.info("email_channel_disconnected", team_id=team.id, user_id=user.id, user_email=user.email)

        return Response({"ok": True})
