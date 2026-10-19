"""Native email-sending integration (SES / maildev) and its cleanup signal."""

from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import models, transaction
from django.db.models import F, Func, JSONField, Q, Value
from django.dispatch import receiver
from django.utils import timezone

from disposable_email_domains import blocklist as disposable_email_domains_list
from free_email_domains import whitelist as free_email_domains_list
from rest_framework.exceptions import ValidationError

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.plugins.plugin_server_api import reload_integrations_on_workers

from . import model

if TYPE_CHECKING:
    from products.workflows.backend.facade.contracts import EmailDomainVerification


VERIFICATION_REQUESTED_AT = "verification_requested_at"


def _with_config_key(key: str, value: object) -> Func:
    return Func(
        F("config"),
        Value([key]),
        Value(value, output_field=JSONField()),
        function="jsonb_set",
        output_field=JSONField(),
    )


def mark_verification_requested(senders: "models.QuerySet[model.Integration]") -> int:
    return senders.update(config=_with_config_key(VERIFICATION_REQUESTED_AT, int(timezone.now().timestamp())))


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
                    "reply_to": config.get("reply_to", ""),
                    "name": name,
                    "provider": provider,
                    "verified": True if provider == "maildev" else False,
                    VERIFICATION_REQUESTED_AT: int(timezone.now().timestamp()),
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
        # Only name, mail_from_subdomain and reply_to can be updated
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
                "reply_to": config.get("reply_to", self.integration.config.get("reply_to", "")),
            }
        )
        self.integration.save()
        reload_integrations_on_workers(self.integration.team_id, [self.integration.id])

        return self.integration

    def apply_verification(self, verification_result: "EmailDomainVerification") -> "EmailDomainVerification":
        if verification_result.get("status") == "success":
            verified_ids = self._mark_matching_senders_verified()
            if verified_ids:
                reload_integrations_on_workers(self.integration.team_id, verified_ids)
        return verification_result

    def _mark_matching_senders_verified(self) -> list[int]:
        with transaction.atomic():
            verified_ids = list(self._matching_senders().select_for_update().values_list("id", flat=True))
            model.Integration.objects.filter(id__in=verified_ids).update(config=_with_config_key("verified", True))
            if self.integration.id in verified_ids:
                from products.workflows.backend.facade.api import (
                    set_default_email_sender_if_unset,  # noqa: PLC0415 — keeps the workflows facade off the model import path
                )

                set_default_email_sender_if_unset(self.integration.team_id, self.integration.id)
        return verified_ids

    def _matching_senders(self) -> "models.QuerySet[model.Integration]":
        mail_from_subdomain = self.integration.config.get("mail_from_subdomain", "feedback")
        matching_mail_from = Q(config__mail_from_subdomain=mail_from_subdomain)
        if mail_from_subdomain == "feedback":
            matching_mail_from |= Q(config__mail_from_subdomain__isnull=True)
        return model.Integration.objects.filter(
            matching_mail_from,
            team_id=self.integration.team_id,
            kind="email",
            config__domain=self.integration.config.get("domain"),
            config__provider=self.integration.config.get("provider", "ses"),
        )

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

        if verification_result.get("status") != "success":
            mark_verification_requested(model.Integration.objects.filter(id=self.integration.id))
        return self.apply_verification(verification_result)


@receiver(models.signals.post_delete, sender=model.Integration)
def clear_default_email_sender_on_integration_delete(sender: Any, instance: model.Integration, **kwargs: Any) -> None:
    if instance.kind != "email":
        return

    from products.workflows.backend.facade.api import (
        clear_default_email_sender,  # noqa: PLC0415 — keeps the workflows facade off the model import path
    )

    clear_default_email_sender(instance.team_id, instance.id)


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
