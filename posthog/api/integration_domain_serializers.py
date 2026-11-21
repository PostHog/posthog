from typing import Any

from django.db import models

from rest_framework import serializers

from posthog.domain_connect import DOMAIN_CONNECT_PROVIDERS


class DomainConnectContextKind(models.TextChoices):
    EMAIL = "email", "Email sending domain"
    PROXY = "proxy", "Reverse proxy domain"


class DomainConnectApplyUrlRequestSerializer(serializers.Serializer):
    context = serializers.ChoiceField(  # type: ignore[assignment]
        choices=DomainConnectContextKind.choices,
        help_text="`email` to configure an email sending domain, `proxy` for a reverse proxy domain.",
        error_messages={
            "required": "context must be 'email' or 'proxy'",
            "invalid_choice": "context must be 'email' or 'proxy'",
        },
    )
    integration_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="ID of the email integration (sender). Required when `context` is `email`.",
    )
    proxy_record_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="ID of the reverse proxy record. Required when `context` is `proxy`.",
    )
    redirect_uri = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Where the DNS host sends the user after they approve. Omit it when handing the URL to a person.",
    )
    provider_endpoint = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text=(
            "Provider endpoint from `available_providers` in the domain-connect check. "
            "Omit it to use the provider detected from the domain's DNS."
        ),
    )

    def validate_provider_endpoint(self, value: str | None) -> str | None:
        if value and value not in DOMAIN_CONNECT_PROVIDERS:
            raise serializers.ValidationError("Unsupported provider endpoint")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["context"] == DomainConnectContextKind.EMAIL and not attrs.get("integration_id"):
            raise serializers.ValidationError("integration_id is required for email context")
        if attrs["context"] == DomainConnectContextKind.PROXY and not attrs.get("proxy_record_id"):
            raise serializers.ValidationError("proxy_record_id is required for proxy context")
        return attrs


class DomainConnectApplyUrlResponseSerializer(serializers.Serializer):
    url = serializers.CharField(
        help_text=(
            "Signed Domain Connect URL. A person opens it, signs in at their DNS host and approves the records. "
            "The records do not change until they approve."
        )
    )
