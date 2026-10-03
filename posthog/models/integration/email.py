"""Native email-sending integration (SES / maildev) and its cleanup signal."""

from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from functools import cached_property
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import connection, models, transaction
from django.dispatch import receiver

from disposable_email_domains import blocklist as disposable_email_domains_list
from free_email_domains import whitelist as free_email_domains_list
from rest_framework.exceptions import ValidationError

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false
from posthog.plugins.plugin_server_api import reload_integrations_on_workers

from . import model

if TYPE_CHECKING:
    from products.workflows.backend.facade.contracts import EmailDomainVerification


DEFAULT_MAIL_FROM_SUBDOMAIN = "feedback"
EMAIL_DOMAIN_AGENT_SETUP_FLAG = "workflows-email-domain-agent-setup"


class EmailIntegration:
    integration: model.Integration

    def __init__(self, integration: model.Integration, acting_user: User | None = None) -> None:
        if integration.kind != "email":
            raise Exception("EmailIntegration init called with Integration with wrong 'kind'")
        self.integration = integration
        self.acting_user = acting_user

    @staticmethod
    def _shares_domain_label_for(team: Team, acting_user: User | None) -> bool:
        return feature_enabled_or_false(
            EMAIL_DOMAIN_AGENT_SETUP_FLAG,
            str(acting_user.distinct_id) if acting_user else str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.uuid)},
            group_properties={"organization": {"id": str(team.organization_id)}, "project": {"id": str(team.uuid)}},
            send_feature_flag_events=False,
        )

    @cached_property
    def _shares_domain_label(self) -> bool:
        return self._shares_domain_label_for(self.integration.team, self.acting_user)

    @property
    def mail_from_subdomain(self) -> str:
        if self._shares_domain_label:
            return self._shared_mail_from_subdomain(self.integration.config)
        return self.integration.config.get("mail_from_subdomain", DEFAULT_MAIL_FROM_SUBDOMAIN)

    @staticmethod
    def _shared_mail_from_subdomain(config: dict[str, Any]) -> str:
        return config.get("mail_from_subdomain") or DEFAULT_MAIL_FROM_SUBDOMAIN

    @classmethod
    def create_native_integration(
        cls, config: dict[str, Any], team_id: int, organization_id: str, created_by: User | None = None
    ) -> model.Integration:
        shares_domain_label = cls._shares_domain_label_for(Team.objects.get(id=team_id), created_by)
        domain_access: AbstractContextManager[None] = (
            cls._exclusive_domain_access(cls._email_domain(config["email"])) if shares_domain_label else nullcontext()
        )
        with domain_access:
            return cls._create_native_integration(
                config, team_id, organization_id, created_by, shares_domain_label=shares_domain_label
            )

    @classmethod
    def _create_native_integration(
        cls,
        config: dict[str, Any],
        team_id: int,
        organization_id: str,
        created_by: User | None,
        *,
        shares_domain_label: bool,
    ) -> model.Integration:
        email_address: str = config["email"].lower()
        name: str = config["name"]
        domain: str = cls._email_domain(email_address)
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

        mail_from_subdomain = (
            cls._domain_wide_mail_from_subdomain(domain, config.get("mail_from_subdomain"), same_domain_integrations)
            if shares_domain_label
            else config.get("mail_from_subdomain", DEFAULT_MAIL_FROM_SUBDOMAIN)
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

    @staticmethod
    def _email_domain(email_address: str) -> str:
        return email_address.lower().split("@")[1]

    @staticmethod
    @contextmanager
    def _exclusive_domain_access(domain: str) -> Iterator[None]:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"email-domain:{domain}"])
            yield

    @contextmanager
    def _domain_guard(self) -> Iterator[None]:
        if not self._shares_domain_label:
            yield
            return
        with self._exclusive_domain_access(self.integration.config["domain"]):
            self.integration.refresh_from_db(fields=["config"])
            yield

    @staticmethod
    def _domain_wide_mail_from_subdomain(
        domain: str, requested_subdomain: str | None, same_domain_integrations: Iterable[model.Integration]
    ) -> str:
        domain_subdomains = {
            EmailIntegration._shared_mail_from_subdomain(integration.config) for integration in same_domain_integrations
        }
        if not domain_subdomains:
            return requested_subdomain or DEFAULT_MAIL_FROM_SUBDOMAIN
        if len(domain_subdomains) > 1:
            raise ValidationError(
                f"Senders on {domain} use different MAIL FROM subdomains. "
                f"Open an existing sender on {domain} in any project of this organization and save the subdomain you want. "
                "Then add this sender."
            )
        domain_subdomain = domain_subdomains.pop()
        if requested_subdomain and requested_subdomain != domain_subdomain:
            raise ValidationError(
                f"{domain} already uses the MAIL FROM subdomain '{domain_subdomain}'. "
                f"Use '{domain_subdomain}' for this sender. To change it for every sender on {domain}, edit an existing sender."
            )
        return domain_subdomain

    def update_native_integration(self, config: dict[str, Any], team_id: int) -> model.Integration:
        with self._domain_guard():
            return self._update_native_integration(config)

    def _update_native_integration(self, config: dict[str, Any]) -> model.Integration:
        provider = self.integration.config.get("provider")
        domain = self.integration.config.get("domain")
        # Only name and mail_from_subdomain can be updated
        name: str = config.get("name", self.integration.config.get("name"))
        mail_from_subdomain = self._edited_mail_from_subdomain(config.get("mail_from_subdomain"))

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
        if self._shares_domain_label:
            self._share_mail_from_subdomain_with_domain_senders(domain, mail_from_subdomain)

        return self.integration

    def reject_address_change(self, email_address: str) -> None:
        if email_address.lower() != self.integration.config.get("email", "").lower():
            raise ValidationError(f"The sender address cannot change. Create a new sender for {email_address} instead.")

    def _edited_mail_from_subdomain(self, requested_subdomain: str | None) -> str:
        if self._shares_domain_label:
            return requested_subdomain or self.mail_from_subdomain
        return self.mail_from_subdomain if requested_subdomain is None else requested_subdomain

    def _share_mail_from_subdomain_with_domain_senders(self, domain: str, mail_from_subdomain: str) -> None:
        domain_senders = (
            model.Integration.objects.select_for_update(of=("self",))
            .filter(
                kind="email",
                config__domain=domain,
                team__organization_id=self.integration.team.organization_id,
            )
            .exclude(pk=self.integration.pk)
        )
        for sender in domain_senders:
            sender.config["mail_from_subdomain"] = mail_from_subdomain
            sender.save(update_fields=["config"])

    def verify(self) -> "EmailDomainVerification":
        with self._domain_guard():
            return self._verify()

    def _verify(self) -> "EmailDomainVerification":
        domain = self.integration.config.get("domain")
        provider = self.integration.config.get("provider", "ses")
        mail_from_subdomain = self.mail_from_subdomain

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

            verified_integration_ids = [integration.id for integration in all_integrations_for_domain]
            transaction.on_commit(
                lambda: reload_integrations_on_workers(self.integration.team_id, verified_integration_ids)
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
