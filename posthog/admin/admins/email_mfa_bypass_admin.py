from typing import cast

from django.contrib import admin
from django.shortcuts import render

from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.helpers.two_factor_session import (
    EMAIL_MFA_BYPASS_REDIS_KEY,
    MAX_EMAIL_MFA_GLOBAL_DISABLE_TTL_SECONDS,
    add_email_mfa_bypass,
    clear_email_mfa_global_disable,
    get_email_mfa_global_disable,
    remove_email_mfa_bypass,
    set_email_mfa_global_disable,
)
from posthog.models.user import User
from posthog.redis import get_client


class EmailMFABypassEmailSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="Email address to bypass email MFA verification")


class EmailMFAGlobalDisableSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=False, help_text="Why email MFA is being disabled globally")
    ttl_seconds = serializers.IntegerField(
        min_value=1,
        max_value=MAX_EMAIL_MFA_GLOBAL_DISABLE_TTL_SECONDS,
        help_text="How long the disable lasts, in seconds (max 7 days)",
    )


class EmailMFAGlobalDisableViewSet(viewsets.ViewSet):
    """Completely disable email MFA verification for all users, with a required reason and TTL."""

    permission_classes = [IsAdminUser]

    def list(self, request: Request) -> Response:
        state = get_email_mfa_global_disable()
        return Response({"disabled": state is not None, "state": state})

    def create(self, request: Request) -> Response:
        serializer = EmailMFAGlobalDisableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        set_email_mfa_global_disable(
            reason=serializer.validated_data["reason"],
            ttl_seconds=serializer.validated_data["ttl_seconds"],
            disabled_by=cast(User, request.user).email,
        )
        return Response({"disabled": True, "state": get_email_mfa_global_disable()}, status=status.HTTP_201_CREATED)

    def destroy(self, request: Request) -> Response:
        clear_email_mfa_global_disable()
        return Response(status=status.HTTP_204_NO_CONTENT)


class EmailMFABypassViewSet(viewsets.ViewSet):
    permission_classes = [IsAdminUser]

    def list(self, request: Request) -> Response:
        bypass_emails = sorted(
            member.decode() if isinstance(member, bytes) else member
            for member in get_client().smembers(EMAIL_MFA_BYPASS_REDIS_KEY)
        )
        return Response(bypass_emails)

    def create(self, request: Request) -> Response:
        serializer = EmailMFABypassEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        add_email_mfa_bypass(email)
        return Response({"email": email}, status=status.HTTP_201_CREATED)

    def destroy(self, request: Request, email: str) -> Response:
        remove_email_mfa_bypass(email)
        return Response(status=status.HTTP_204_NO_CONTENT)


def email_mfa_bypass_view(request):
    """Admin template view — thin wrapper that renders the HTML admin page."""
    bypass_emails = sorted(
        member.decode() if isinstance(member, bytes) else member
        for member in get_client().smembers(EMAIL_MFA_BYPASS_REDIS_KEY)
    )

    context = {
        "bypass_emails": bypass_emails,
        "global_disable": get_email_mfa_global_disable(),
        "title": "Email MFA bypass",
        "has_view_permission": True,
        "site_title": admin.site.site_title,
        "site_header": admin.site.site_header,
        "site_url": admin.site.site_url,
        "has_permission": True,
    }
    return render(request, "admin/email_mfa_bypass.html", context)
