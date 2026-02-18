from django.contrib import admin
from django.shortcuts import render

from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.redis import get_client
from posthog.workos_radar import WORKOS_RADAR_BYPASS_REDIS_KEY, add_radar_bypass_email, remove_radar_bypass_email


class RadarBypassEmailSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="Email address to bypass suspicious signup checks")


class RadarBypassViewSet(viewsets.ViewSet):
    permission_classes = [IsAdminUser]

    def list(self, request: Request) -> Response:
        bypass_emails = sorted(
            member.decode() if isinstance(member, bytes) else member
            for member in get_client().smembers(WORKOS_RADAR_BYPASS_REDIS_KEY)
        )
        return Response(bypass_emails)

    def create(self, request: Request) -> Response:
        serializer = RadarBypassEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        add_radar_bypass_email(email)
        return Response({"email": email}, status=status.HTTP_201_CREATED)

    def destroy(self, request: Request, email: str) -> Response:
        remove_radar_bypass_email(email)
        return Response(status=status.HTTP_204_NO_CONTENT)


def radar_bypass_view(request):
    """Admin template view — thin wrapper that renders the HTML admin page."""
    bypass_emails = sorted(
        member.decode() if isinstance(member, bytes) else member
        for member in get_client().smembers(WORKOS_RADAR_BYPASS_REDIS_KEY)
    )

    context = {
        "bypass_emails": bypass_emails,
        "title": "Suspicious signup checks bypass",
        "has_view_permission": True,
        "site_title": admin.site.site_title,
        "site_header": admin.site.site_header,
        "site_url": admin.site.site_url,
        "has_permission": True,
    }
    return render(request, "admin/radar_bypass.html", context)
