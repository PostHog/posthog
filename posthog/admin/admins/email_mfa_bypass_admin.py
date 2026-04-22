from django.contrib import admin
from django.shortcuts import render

from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.helpers.two_factor_session import EMAIL_MFA_BYPASS_REDIS_KEY, add_email_mfa_bypass, remove_email_mfa_bypass
from posthog.redis import get_client


class EmailMFABypassEmailSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="Email address to bypass email MFA verification")


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
        "title": "Email MFA bypass",
        "has_view_permission": True,
        "site_title": admin.site.site_title,
        "site_header": admin.site.site_header,
        "site_url": admin.site.site_url,
        "has_permission": True,
    }
    return render(request, "admin/email_mfa_bypass.html", context)
