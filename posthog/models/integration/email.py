"""Native email-sending integration (SES / maildev) and its cleanup signal."""

from typing import Any

from django.conf import settings
from django.db import models, transaction
from django.dispatch import receiver

from disposable_email_domains import blocklist as disposable_email_domains_list
from free_email_domains import whitelist as free_email_domains_list
from rest_framework.exceptions import ValidationError

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.plugins.plugin_server_api import reload_integrations_on_workers

from products.workflows.backend.providers import MAILDEV_MOCK_DNS_RECORDS, SESProvider

from . import model


class EmailIntegration:
    integration: model.Integration

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != "email":
            raise Exception("EmailIntegration init called with Integration with wrong 'kind'")
        self.integration = integration

    @property
    def ses_provider(self) -> SESProvider:
        return SESProvider()

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
            ses = SESProvider()
            org_team_ids = list(Team.objects.filter(organization_id=organization_id).values_list("id", flat=True))
            ses.create_email_domain(
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
            ses = SESProvider()
            ses.update_mail_from_subdomain(domain, mail_from_subdomain=mail_from_subdomain)
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

    def verify(self):
        domain = self.integration.config.get("domain")
        provider = self.integration.config.get("provider", "ses")
        mail_from_subdomain = self.integration.config.get("mail_from_subdomain", "feedback")

        # Use the appropriate provider for verification
        if provider == "ses":
            verification_result = self.ses_provider.verify_email_domain(
                domain, mail_from_subdomain=mail_from_subdomain, team_id=self.integration.team_id
            )
        elif provider == "maildev":
            verification_result = {
                "status": "success",
                "dnsRecords": MAILDEV_MOCK_DNS_RECORDS,
            }
        else:
            raise ValueError(f"Invalid provider: {provider}")

        if verification_result.get("status") == "success":
            # We can validate all other integrations with the same domain and provider
            all_integrations_for_domain = model.Integration.objects.filter(
                team_id=self.integration.team_id,
                kind="email",
                config__domain=domain,
                config__provider=provider,
            )
            for integration in all_integrations_for_domain:
                integration.config["verified"] = True
                integration.save()

            reload_integrations_on_workers(
                self.integration.team_id, [integration.id for integration in all_integrations_for_domain]
            )

        return verification_result


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
