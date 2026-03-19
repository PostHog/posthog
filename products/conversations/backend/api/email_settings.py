"""Email channel settings API for connect/disconnect flows."""

import secrets

from django.db import IntegrityError, transaction

import structlog
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.instance_setting import get_instance_setting
from posthog.models.user import User

from products.conversations.backend.models import TeamConversationsEmailConfig

logger = structlog.get_logger(__name__)


class EmailConnectSerializer(serializers.Serializer):
    from_email = serializers.EmailField()
    from_name = serializers.CharField(max_length=255)


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
            }
        )


class EmailConnectView(APIView):
    permission_classes = [IsAuthenticated]

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

        def _enable_email_on_team() -> None:
            s = team.conversations_settings or {}
            s["email_enabled"] = True
            team.conversations_settings = s
            team.save(update_fields=["conversations_settings"])

        try:
            with transaction.atomic():
                config = TeamConversationsEmailConfig.objects.select_for_update().get(team=team)
                config.from_email = from_email
                config.from_name = from_name
                config.domain = domain
                config.save(update_fields=["from_email", "from_name", "domain"])
                _enable_email_on_team()
        except TeamConversationsEmailConfig.DoesNotExist:
            try:
                with transaction.atomic():
                    config = TeamConversationsEmailConfig.objects.create(
                        team=team,
                        inbound_token=secrets.token_hex(16),
                        from_email=from_email,
                        from_name=from_name,
                        domain=domain,
                    )
                    _enable_email_on_team()
            except IntegrityError:
                with transaction.atomic():
                    config = TeamConversationsEmailConfig.objects.select_for_update().get(team=team)
                    config.from_email = from_email
                    config.from_name = from_name
                    config.domain = domain
                    config.save(update_fields=["from_email", "from_name", "domain"])
                    _enable_email_on_team()

        forwarding_address = f"team-{config.inbound_token}@{inbound_domain}"

        logger.info("email_channel_connected", team_id=team.id, domain=domain, user_id=user.id, user_email=user.email)

        return Response(
            {
                "ok": True,
                "forwarding_address": forwarding_address,
                "from_email": from_email,
                "from_name": from_name,
                "domain": domain,
            }
        )


class EmailDisconnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, *args, **kwargs) -> Response:
        user = request.user
        if not isinstance(user, User) or user.current_team is None:
            return Response({"error": "No current team selected"}, status=400)

        team = user.current_team

        with transaction.atomic():
            try:
                config = TeamConversationsEmailConfig.objects.get(team=team)
                config.delete()
            except TeamConversationsEmailConfig.DoesNotExist:
                pass

            settings = team.conversations_settings or {}
            settings["email_enabled"] = False
            team.conversations_settings = settings
            team.save(update_fields=["conversations_settings"])

        logger.info("email_channel_disconnected", team_id=team.id, user_id=user.id, user_email=user.email)

        return Response({"ok": True})
