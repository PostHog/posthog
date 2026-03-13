"""Email channel settings API endpoints."""

import secrets

import structlog
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.instance_setting import get_instance_setting
from posthog.models.user import User

from products.conversations.backend import mailgun
from products.conversations.backend.models import TeamConversationsEmailConfig

logger = structlog.get_logger(__name__)


class EmailConnectSerializer(serializers.Serializer):
    from_email = serializers.EmailField(help_text="Support email address (e.g. support@company.com)")
    from_name = serializers.CharField(max_length=255, help_text="Display name for outbound emails")


class EmailTestSerializer(serializers.Serializer):
    test_email = serializers.EmailField(help_text="Email address to send a test email to")


def _get_team(request: Request):
    user = request.user
    if not isinstance(user, User) or user.current_team is None:
        return None
    return user.current_team


class EmailConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        team = _get_team(request)
        if not team:
            return Response({"error": "No current team selected"}, status=400)

        if TeamConversationsEmailConfig.objects.filter(team=team).exists():
            return Response({"error": "Email is already connected. Disconnect first."}, status=400)

        serializer = EmailConnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from_email: str = serializer.validated_data["from_email"]
        from_name: str = serializer.validated_data["from_name"]
        domain = from_email.split("@")[1]

        inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN")
        if not inbound_domain:
            return Response({"error": "Email inbound domain is not configured on this instance."}, status=400)

        inbound_token = secrets.token_hex(16)

        dns_records: dict = {}
        try:
            dns_records = mailgun.add_domain(domain)
        except Exception:
            logger.exception("email_connect_add_domain_failed", domain=domain, team_id=team.id)
            try:
                info = mailgun.get_domain_info(domain)
                dns_records = {
                    "sending_dns_records": info.get("sending_dns_records", []),
                    "receiving_dns_records": info.get("receiving_dns_records", []),
                }
            except Exception:
                logger.exception("email_connect_get_domain_failed", domain=domain, team_id=team.id)

        config = TeamConversationsEmailConfig.objects.create(
            team=team,
            inbound_token=inbound_token,
            from_email=from_email,
            from_name=from_name,
            domain=domain,
            domain_verified=False,
            dns_records=dns_records,
        )

        settings_dict = team.conversations_settings or {}
        settings_dict["email_enabled"] = True
        team.conversations_settings = settings_dict
        team.save(update_fields=["conversations_settings"])

        inbound_address = f"team-{inbound_token}@{inbound_domain}"

        return Response(
            {
                "inbound_address": inbound_address,
                "from_email": config.from_email,
                "from_name": config.from_name,
                "domain": config.domain,
                "domain_verified": config.domain_verified,
                "dns_records": config.dns_records,
            }
        )


class EmailVerifyDomainView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        team = _get_team(request)
        if not team:
            return Response({"error": "No current team selected"}, status=400)

        try:
            config = TeamConversationsEmailConfig.objects.get(team=team)
        except TeamConversationsEmailConfig.DoesNotExist:
            return Response({"error": "Email is not connected."}, status=400)

        try:
            verified = mailgun.verify_domain(config.domain)
        except Exception:
            logger.exception("email_verify_domain_failed", domain=config.domain, team_id=team.id)
            return Response({"domain_verified": False, "error": "Verification check failed."}, status=500)

        if verified != config.domain_verified:
            config.domain_verified = verified
            config.save(update_fields=["domain_verified"])

        return Response(
            {
                "domain": config.domain,
                "domain_verified": config.domain_verified,
            }
        )


class EmailTestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        team = _get_team(request)
        if not team:
            return Response({"error": "No current team selected"}, status=400)

        try:
            config = TeamConversationsEmailConfig.objects.get(team=team)
        except TeamConversationsEmailConfig.DoesNotExist:
            return Response({"error": "Email is not connected."}, status=400)

        if not config.domain_verified:
            return Response({"error": "Domain is not verified yet. Add DNS records and verify first."}, status=400)

        serializer = EmailTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        test_email: str = serializer.validated_data["test_email"]

        try:
            from django.conf import settings as django_settings
            from django.core import mail
            from django.core.mail.backends.smtp import EmailBackend
            from django.utils.module_loading import import_string

            from_email = f'"{config.from_name}" <{config.from_email}>'
            msg = mail.EmailMultiAlternatives(
                subject="Test email from PostHog Conversations",
                body="This is a test email to verify your email channel configuration is working correctly.",
                from_email=from_email,
                to=[test_email],
            )
            msg.attach_alternative(
                "<p>This is a test email to verify your email channel configuration is working correctly.</p>",
                "text/html",
            )

            klass = import_string(django_settings.EMAIL_BACKEND) if django_settings.EMAIL_BACKEND else EmailBackend
            connection = klass(
                host=get_instance_setting("EMAIL_HOST"),
                port=get_instance_setting("EMAIL_PORT"),
                username=get_instance_setting("EMAIL_HOST_USER"),
                password=get_instance_setting("EMAIL_HOST_PASSWORD"),
                use_tls=get_instance_setting("EMAIL_USE_TLS"),
                use_ssl=get_instance_setting("EMAIL_USE_SSL"),
            )
            connection.open()
            connection.send_messages([msg])
            connection.close()
        except Exception:
            logger.exception("email_test_send_failed", team_id=team.id, test_email=test_email)
            return Response({"error": "Failed to send test email. Check SMTP settings."}, status=500)

        return Response({"success": True, "message": f"Test email sent to {test_email}."})


class EmailDisconnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        team = _get_team(request)
        if not team:
            return Response({"error": "No current team selected"}, status=400)

        try:
            config = TeamConversationsEmailConfig.objects.get(team=team)
        except TeamConversationsEmailConfig.DoesNotExist:
            return Response({"error": "Email is not connected."}, status=400)

        try:
            mailgun.delete_domain(config.domain)
        except Exception:
            logger.exception("email_disconnect_delete_domain_failed", domain=config.domain)

        config.delete()

        settings_dict = team.conversations_settings or {}
        settings_dict["email_enabled"] = False
        team.conversations_settings = settings_dict
        team.save(update_fields=["conversations_settings"])

        return Response({"success": True})


class EmailStatusView(APIView):
    """Get current email channel configuration status."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        team = _get_team(request)
        if not team:
            return Response({"error": "No current team selected"}, status=400)

        try:
            config = TeamConversationsEmailConfig.objects.get(team=team)
        except TeamConversationsEmailConfig.DoesNotExist:
            return Response({"connected": False})

        inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN") or ""
        inbound_address = f"team-{config.inbound_token}@{inbound_domain}" if inbound_domain else ""

        return Response(
            {
                "connected": True,
                "inbound_address": inbound_address,
                "from_email": config.from_email,
                "from_name": config.from_name,
                "domain": config.domain,
                "domain_verified": config.domain_verified,
                "dns_records": config.dns_records,
            }
        )
