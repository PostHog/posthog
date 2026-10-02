from rest_framework import serializers

from products.workflows.backend.facade.enums import (
    EmailDomainSetupRecordKind,
    EmailDomainSetupRecordStatus,
    EmailDomainSetupRecordType,
    EmailDomainSetupStatus,
    EmailDomainSetupStepKey,
    EmailDomainSetupStepState,
)


class EmailDomainStatusQuerySerializer(serializers.Serializer):
    refresh = serializers.BooleanField(
        default=False,
        help_text="Skip the 10 second status cache and read SES and DNS again. Use it after changing DNS records.",
    )


class EmailDomainStatusStepSerializer(serializers.Serializer):
    key = serializers.ChoiceField(
        choices=EmailDomainSetupStepKey.choices,
        help_text="The setup step: domain_added (SES knows the domain), records_found (every DNS record is "
        "published), verified (SES verified the domain and the sender can send).",
    )
    state = serializers.ChoiceField(choices=EmailDomainSetupStepState.choices, help_text="Progress of this step.")


class EmailDomainStatusRecordSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=EmailDomainSetupRecordKind.choices,
        help_text="What the record does: verification proves domain ownership, dkim signs email, spf and "
        "mail_from_spf list SES as an allowed sender, mail_from_mx routes bounces, dmarc sets the policy for "
        "unauthenticated mail.",
    )
    hostname = serializers.CharField(help_text="Full DNS name to create the record at, including the domain.")
    type = serializers.ChoiceField(choices=EmailDomainSetupRecordType.choices, help_text="DNS record type.")
    value = serializers.CharField(
        help_text="Value to publish. For an SPF record, add the include to an existing SPF record instead of "
        "creating a second one. For DMARC, any existing v=DMARC1 record counts."
    )
    priority = serializers.IntegerField(allow_null=True, help_text="MX priority. Null for other record types.")
    status = serializers.ChoiceField(
        choices=EmailDomainSetupRecordStatus.choices,
        help_text="pending: not found in DNS yet. found: published in DNS, SES has not confirmed it yet. "
        "verified: SES confirmed the record, or for DMARC a v=DMARC1 record exists.",
    )


class EmailDomainStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        source="check.status",
        choices=EmailDomainSetupStatus.choices,
        help_text="Overall setup status. records_found means every record is published and SES has not "
        "confirmed yet. temporary_failure means SES could not see the records, usually because DNS changes "
        "have not spread yet. failed means SES gave up after 72 hours; start verification again.",
    )
    verified = serializers.BooleanField(
        help_text="Whether the sender can send email. Set once SES verifies the domain."
    )
    checked_at = serializers.DateTimeField(
        help_text="When SES and DNS were read. Responses are cached for 10 seconds unless refresh is set."
    )
    steps = EmailDomainStatusStepSerializer(
        source="check.steps", many=True, help_text="The three setup steps, in order."
    )
    records = EmailDomainStatusRecordSerializer(
        source="check.records",
        many=True,
        help_text="DNS records to publish at the domain's DNS host, with the status of each. Empty when "
        "status is not_started.",
    )


class EmailDomainDnsHostSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Name of the company that hosts the domain's DNS, such as Cloudflare.")
    dns_settings_url = serializers.URLField(help_text="Link to the DNS settings page at that host.")


class EmailDomainConnectProviderSerializer(serializers.Serializer):
    endpoint = serializers.CharField(help_text="Domain Connect endpoint of the provider.")
    name = serializers.CharField(help_text="Display name of the provider.")


class EmailDomainConnectCheckSerializer(serializers.Serializer):
    supported = serializers.BooleanField(
        help_text="Whether the domain's DNS provider supports automatic setup through Domain Connect."
    )
    provider_name = serializers.CharField(
        allow_null=True, help_text="Domain Connect provider that hosts the domain. Null when not supported."
    )
    available_providers = EmailDomainConnectProviderSerializer(
        many=True,
        help_text="Providers the user can pick manually when automatic detection fails. Empty when supported.",
    )
    dns_host = EmailDomainDnsHostSerializer(
        allow_null=True, help_text="The detected DNS host of the root domain, from its nameservers. Null when unknown."
    )
    existing_email_tools = serializers.ListField(
        child=serializers.CharField(),
        help_text="Email tools that already send for the root domain, detected from SPF and DKIM records. Best "
        "effort, empty when none are found.",
    )
