"""Native email-sending integration (SES / maildev) and its cleanup signal."""

from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import models, transaction
from django.db.models import F, Func, JSONField, Q, Value
from django.dispatch import receiver

from disposable_email_domains import blocklist as disposable_email_domains_list
from free_email_domains import whitelist as free_email_domains_list
from rest_framework.exceptions import ValidationError

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.plugins.plugin_server_api import reload_integrations_on_workers

from . import model

if TYPE_CHECKING:
    from products.workflows.backend.facade.contracts import EmailDomainVerification


class EmailIntegration:
    integration: model.Integration

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != "email":
            raise Exception("EmailIntegration init called with Integration with wrong 'kind'")
        self.integration = integration

    @classmethod
    def create_native_integration(
        cls, config: dict, team_id: int, organization_id: str, created_by: User | None = None
    ) -> model.Integration:
        email_address: str = config["email"].lower()
        name: str = config["name"]
        domain: str = email_address.split("@")[1]
        mail_from_subdomain: str = config.get("mail_from_subdomain", "feedback")
        provider: str = config.get("provider", "ses")

        if domain in free_email_domains_list or domain in disposable_email_domains_list:
            raise ValidationError(f"Email domain {domain} is not supported. Please use a custom domain.")

        # Check if any other integration already exists in a different team with the same domain,
        # if so, ensure this team is part of the same organization. If not, we block creation.
        same_domain_integrations = model.Integration.objects.filter(kind="email", config__domain=domain)
        for integration in same_domain_integrations:
            if str(integration.team.organization.id) != str(organization_id):
                raise ValidationError(
                    f"An email integration with domain {domain} already exists in another organization. Try a different domain or contact support if you believe this is a mistake."
                )

        # Create domain in the appropriate provider
        if provider == "ses":
            from products.workflows.backend.facade.api import (
                create_ses_email_domain,  # noqa: PLC0415 — keeps the workflows facade off the model import path
            )

            org_team_ids = list(Team.objects.filter(organization_id=organization_id).values_list("id", flat=True))
            create_ses_email_domain(
                domain,
                mail_from_subdomain=mail_from_subdomain,
                team_id=team_id,
                org_team_ids=org_team_ids,
            )
        elif provider == "maildev" and settings.DEBUG:
            pass
        else:
            raise ValueError(f"Invalid provider: must be 'ses'")

        integration, created = model.Integration.objects.update_or_create(
            team_id=team_id,
            kind="email",
            integration_id=email_address,
            defaults={
                "config": {
                    "email": email_address,
                    "domain": domain,
                    "mail_from_subdomain": mail_from_subdomain,
                    "name": name,
                    "provider": provider,
                    "verified": True if provider == "maildev" else False,
                },
                "created_by": created_by,
            },
        )

        if integration.errors:
            integration.errors = ""
            integration.save()

        return integration

    def update_native_integration(self, config: dict, team_id: int) -> model.Integration:
        provider = self.integration.config.get("provider")
        domain = self.integration.config.get("domain")
        # Only name and mail_from_subdomain can be updated
        name: str = config.get("name", self.integration.config.get("name"))
        mail_from_subdomain: str = config.get(
            "mail_from_subdomain", self.integration.config.get("mail_from_subdomain", "feedback")
        )

        # Update domain in the appropriate provider
        if provider == "ses":
            from products.workflows.backend.facade.api import (
                update_ses_mail_from_subdomain,  # noqa: PLC0415 — keeps the workflows facade off the model import path
            )

            update_ses_mail_from_subdomain(domain, mail_from_subdomain=mail_from_subdomain)
        elif provider == "maildev" and settings.DEBUG:
            pass
        else:
            raise ValueError(f"Invalid provider: must be 'ses'")

        self.integration.config.update(
            {
                "name": name,
                "mail_from_subdomain": mail_from_subdomain,
            }
        )
        self.integration.save()

        return self.integration

    def _apply_verification(self, verification_result: "EmailDomainVerification") -> "EmailDomainVerification":
        if verification_result.get("status") == "success":
            mail_from_subdomain = self.integration.config.get("mail_from_subdomain", "feedback")
            matching_mail_from = Q(config__mail_from_subdomain=mail_from_subdomain)
            if mail_from_subdomain == "feedback":
                matching_mail_from |= Q(config__mail_from_subdomain__isnull=True)
            all_integrations_for_domain = model.Integration.objects.filter(
                matching_mail_from,
                team_id=self.integration.team_id,
                kind="email",
                config__domain=self.integration.config.get("domain"),
                config__provider=self.integration.config.get("provider", "ses"),
            )
            integration_ids = list(all_integrations_for_domain.values_list("id", flat=True))
            updated = all_integrations_for_domain.update(
                config=Func(
                    F("config"),
                    Value(["verified"]),
                    Value(True, output_field=JSONField()),
                    function="jsonb_set",
                    output_field=JSONField(),
                )
            )
            if updated:
                reload_integrations_on_workers(self.integration.team_id, integration_ids)

        return verification_result

    def refresh_verification(self) -> "EmailDomainVerification":
        from products.workflows.backend.facade.email import get_ses_email_domain_verification

        verification_result = get_ses_email_domain_verification(
            self.integration.config["domain"],
            mail_from_subdomain=self.integration.config.get("mail_from_subdomain", "feedback"),
            team_id=self.integration.team_id,
        )
        return self._apply_verification(verification_result)

    def verify(self) -> "EmailDomainVerification":
        domain = self.integration.config.get("domain")
        provider = self.integration.config.get("provider", "ses")
        mail_from_subdomain = self.integration.config.get("mail_from_subdomain", "feedback")

        verification_result: EmailDomainVerification
        # Use the appropriate provider for verification
        if provider == "ses":
            from products.workflows.backend.facade.api import (
                verify_ses_email_domain,  # noqa: PLC0415 — keeps the workflows facade off the model import path
            )

            verification_result = verify_ses_email_domain(
                domain, mail_from_subdomain=mail_from_subdomain, team_id=self.integration.team_id
            )
        elif provider == "maildev":
            from products.workflows.backend.facade.api import (
                get_maildev_mock_dns_records,  # noqa: PLC0415 — keeps the workflows facade off the model import path
            )

            verification_result = {
                "status": "success",
                "dnsRecords": get_maildev_mock_dns_records(),
            }
        else:
            raise ValueError(f"Invalid provider: {provider}")

        return self._apply_verification(verification_result)


@receiver(models.signals.post_delete, sender=model.Integration)
def cleanup_ses_identity_on_integration_delete(sender: Any, instance: model.Integration, **kwargs: Any) -> None:
    # A post_delete signal (rather than viewset perform_destroy) so SES identities are
    # also cleaned up when integrations die via cascade, e.g. project or org deletion.
    # Leaving the identity behind permanently blocks the domain for every other
    # organization via the foreign-tenant guard in SESProvider.create_email_domain.
    if instance.kind != "email" or instance.config.get("provider") != "ses":
        return
    domain = instance.config.get("domain")
    if not domain:
        return

    from posthog.tasks.integrations import (
        delete_ses_identity_if_unused,  # noqa: PLC0415 - breaks circular import with the tasks module
    )

    transaction.on_commit(lambda: delete_ses_identity_if_unused.delay(domain))
