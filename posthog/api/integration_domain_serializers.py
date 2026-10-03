from typing import Any

from django.conf import settings
from django.db import models

from rest_framework import serializers

from posthog.domain_connect import DOMAIN_CONNECT_PROVIDERS


class NativeEmailProvider(models.TextChoices):
    SES = "ses", "Amazon SES"
    MAILDEV = "maildev", "Maildev (local development only)"


class EmailDomainRecordPurpose(models.TextChoices):
    VERIFICATION = "verification", "Domain ownership or SPF"
    DKIM = "dkim", "DKIM signing"
    MAIL_FROM = "mail_from", "Custom MAIL FROM"
    DMARC = "dmarc", "DMARC policy"


class EmailDomainRecordType(models.TextChoices):
    TXT = "TXT", "TXT record"
    CNAME = "CNAME", "CNAME record"
    MX = "MX", "MX record"


class EmailDomainRecordStatus(models.TextChoices):
    SUCCESS = "success", "Record found"
    PENDING = "pending", "Record not found yet"


class EmailDomainStatus(models.TextChoices):
    SUCCESS = "success", "Domain verified"
    PENDING = "pending", "Verification pending"
    FAILED = "failed", "Verification failed"


class DomainConnectContextKind(models.TextChoices):
    EMAIL = "email", "Email sending domain"
    PROXY = "proxy", "Reverse proxy domain"


class NativeEmailIntegrationSerializer(serializers.Serializer):
    email = serializers.EmailField(
        help_text=(
            "Sender address, for example `hello@mail.example.com`. Its domain is the sending domain that needs "
            "DNS records. Free and disposable mailbox domains such as gmail.com are rejected. "
            "Cannot be changed after creation; send the current address when updating."
        )
    )
    name = serializers.CharField(help_text="Sender display name recipients see in their inbox, for example `Acme`.")
    provider = serializers.ChoiceField(
        choices=NativeEmailProvider.choices,
        help_text="Sending provider. Always `ses`. `maildev` is only accepted in local development.",
    )
    mail_from_subdomain = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=(
            "Subdomain of the sending domain used as the custom MAIL FROM (bounce) domain. "
            "`feedback` gives `feedback.mail.example.com`. Defaults to `feedback`. "
            "Pick another value if that subdomain already has MX records."
        ),
    )

    def validate_email(self, value: str) -> str:
        return value.lower()

    def validate_provider(self, value: str) -> str:
        if value == NativeEmailProvider.MAILDEV and not settings.DEBUG:
            raise serializers.ValidationError(f'"{value}" is not a valid choice.', code="invalid_choice")
        return value


class EmailSenderUpdateRequestSerializer(serializers.Serializer):
    config = NativeEmailIntegrationSerializer(
        help_text="The full sender config. Only `name` and `mail_from_subdomain` change; `email` must stay the same."
    )


class EmailDomainDnsRecordSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=EmailDomainRecordPurpose.choices,
        help_text=(
            "What the record is for: domain ownership or the sending domain's SPF, DKIM signing, "
            "the custom MAIL FROM domain, or DMARC."
        ),
    )
    recordType = serializers.ChoiceField(choices=EmailDomainRecordType.choices, help_text="DNS record type.")
    recordHostname = serializers.CharField(
        help_text=(
            "Fully qualified record name, or `@` for the sending domain itself. "
            "Many DNS hosts append the zone, so enter only the part before it."
        )
    )
    recordValue = serializers.CharField(help_text="Exact record value to publish.")
    status = serializers.ChoiceField(
        choices=EmailDomainRecordStatus.choices,
        help_text="`success` once the record is visible in DNS, `pending` until then.",
    )
    priority = serializers.IntegerField(required=False, help_text="MX priority. Only present on MX records.")


class EmailDomainVerificationSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=EmailDomainStatus.choices,
        help_text=(
            "`success` when every record is verified and the sender can send. `pending` while DNS is not visible "
            "yet, which can take minutes and up to 72 hours. `failed` when the provider gave up on the records."
        ),
    )
    dnsRecords = EmailDomainDnsRecordSerializer(
        many=True, help_text="Every DNS record the sending domain needs, each with its own status."
    )


class DomainConnectCheckQuerySerializer(serializers.Serializer):
    domain = serializers.CharField(
        help_text="Domain to check, for example `mail.example.com`. Subdomains resolve to their registrable domain.",
        error_messages={
            "required": "domain query parameter is required",
            "blank": "domain query parameter is required",
        },
    )


class DomainConnectProviderSerializer(serializers.Serializer):
    endpoint = serializers.CharField(help_text="Provider endpoint. Pass it as `provider_endpoint` to apply-url.")
    name = serializers.CharField(help_text="Provider display name, for example `Cloudflare`.")


class DomainConnectCheckResponseSerializer(serializers.Serializer):
    supported = serializers.BooleanField(
        help_text="True when the domain's DNS host supports one-click setup with Domain Connect."
    )
    provider_name = serializers.CharField(
        allow_null=True, help_text="Detected DNS host, for example `Cloudflare`. Null when not supported."
    )
    available_providers = DomainConnectProviderSerializer(
        many=True,
        help_text=(
            "Providers the user can pick by hand when detection fails. Empty when detection succeeded. "
            "Only offer one if the user confirms their DNS is hosted there."
        ),
    )


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
