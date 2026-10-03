"""Native email-sending integration (SES / maildev) and its cleanup signal."""

import json
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from datetime import datetime
from functools import cached_property
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.cache import cache
from django.db import connection, models, transaction
from django.dispatch import receiver
from django.utils import timezone

import structlog
from disposable_email_domains import blocklist as disposable_email_domains_list
from free_email_domains import whitelist as free_email_domains_list
from rest_framework.exceptions import ValidationError

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.integrations.contracts import IntegrationRecord
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false
from posthog.plugins.plugin_server_api import reload_integrations_on_workers

from . import model

if TYPE_CHECKING:
    from products.workflows.backend.facade.contracts import EmailDomainCheck, EmailDomainVerification

logger = structlog.get_logger(__name__)

EMAIL_DOMAIN_STATUS_CACHE_SECONDS = 10
DEFAULT_MAIL_FROM_SUBDOMAIN = "feedback"
EMAIL_FROM_CODE_FLAG = "workflows-email-from-code"


def email_from_code_enabled(team: Team, acting_user: User | None) -> bool:
    return feature_enabled_or_false(
        EMAIL_FROM_CODE_FLAG,
        str(acting_user.distinct_id) if acting_user else str(team.uuid),
        groups={"organization": str(team.organization_id), "project": str(team.uuid)},
        group_properties={"organization": {"id": str(team.organization_id)}, "project": {"id": str(team.uuid)}},
        send_feature_flag_events=False,
    )


@frozen
class EmailDomainStatusReport:
    check: "EmailDomainCheck"
    verified: bool
    checked_at: datetime


class EmailIntegration:
    integration: model.Integration

    def __init__(self, integration: IntegrationRecord, acting_user: User | None = None) -> None:
        if integration.kind != "email":
            raise Exception("EmailIntegration init called with Integration with wrong 'kind'")
        self.integration = model.integration_model(integration)
        self.acting_user = acting_user

    @cached_property
    def _shares_domain_label(self) -> bool:
        return email_from_code_enabled(self.integration.team, self.acting_user)

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
        shares_domain_label = email_from_code_enabled(Team.objects.get(id=team_id), created_by)
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
                    "reply_to": config.get("reply_to", ""),
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

    def _after_domain_guard(self, callback: Callable[[], None]) -> None:
        if self._shares_domain_label:
            transaction.on_commit(callback)
        else:
            callback()

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
        # Only name, mail_from_subdomain, reply_to and setup_method can be updated
        name: str = config.get("name", self.integration.config.get("name"))
        mail_from_subdomain = self._edited_mail_from_subdomain(config.get("mail_from_subdomain"))

        mail_from_changed = mail_from_subdomain != self.mail_from_subdomain

        if provider == "ses":
            if mail_from_changed:
                from products.workflows.backend.facade.api import (
                    update_ses_mail_from_subdomain,  # noqa: PLC0415 — keeps the workflows facade off the model import path
                )

                update_ses_mail_from_subdomain(domain, mail_from_subdomain=mail_from_subdomain)
        elif provider == "maildev" and settings.DEBUG:
            pass
        else:
            raise ValueError(f"Invalid provider: must be 'ses'")

        changes: dict[str, str] = {
            "name": name,
            "mail_from_subdomain": mail_from_subdomain,
            "reply_to": config.get("reply_to", self.integration.config.get("reply_to", "")),
        }
        if setup_method := config.get("setup_method"):
            changes["setup_method"] = setup_method
        # The row is reread under a lock so a concurrent verification write is not overwritten.
        with transaction.atomic():
            locked = model.Integration.objects.select_for_update().get(id=self.integration.id)
            locked.config.update(changes)
            locked.save(update_fields=["config"])
            if self._shares_domain_label:
                self._share_mail_from_subdomain_with_domain_senders(domain, mail_from_subdomain)
        self.integration.config = locked.config
        self._after_domain_guard(
            lambda: reload_integrations_on_workers(self.integration.team_id, [self.integration.id])
        )

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
            .order_by("id")
        )
        for sender in domain_senders:
            sender.config["mail_from_subdomain"] = mail_from_subdomain
            sender.save(update_fields=["config"])

    def verify(self, *, on_domain_verified: Callable[[], None] | None = None) -> "EmailDomainVerification":
        with self._domain_guard():
            return self._verify(on_domain_verified)

    def _verify(self, on_domain_verified: Callable[[], None] | None) -> "EmailDomainVerification":
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
            self._mark_domain_verified(on_domain_verified)

        return verification_result

    def status(
        self,
        *,
        refresh: bool,
    ) -> EmailDomainStatusReport:
        from products.workflows.backend.facade.contracts import (
            EmailDomainCheck,  # noqa: PLC0415 — keeps the workflows facade off the model import path
        )

        cache_key = f"email_domain_status:{self.integration.id}"
        if not refresh and isinstance(cached := self._cached_status(cache_key), str):
            entry = json.loads(cached)
            return EmailDomainStatusReport(
                check=EmailDomainCheck.from_json(entry["check"]),
                verified=bool(entry["verified"]),
                checked_at=datetime.fromisoformat(entry["checked_at"]),
            )

        check = self._check_domain()
        # Reading the status never saves the verification. The caller records it with verify().
        unrecorded_verification = check.is_verified and not self.integration.config.get("verified")

        report = EmailDomainStatusReport(
            check=check, verified=bool(self.integration.config.get("verified")), checked_at=timezone.now()
        )
        if check.every_dns_lookup_answered and not unrecorded_verification:
            entry = {"check": check.to_json(), "verified": report.verified, "checked_at": report.checked_at.isoformat()}
            try:
                cache.set(cache_key, json.dumps(entry), EMAIL_DOMAIN_STATUS_CACHE_SECONDS)
            except Exception:
                logger.warning("email_domain_status_cache_write_failed", exc_info=True)
        return report

    # The cache only spares SES and DNS reads, so a cache outage falls back to a live check instead of failing.
    @staticmethod
    def _cached_status(cache_key: str) -> object:
        try:
            return cache.get(cache_key)
        except Exception:
            logger.warning("email_domain_status_cache_read_failed", exc_info=True)
            return None

    def _check_domain(self) -> "EmailDomainCheck":
        domain = self.integration.config["domain"]
        mail_from_subdomain = self.mail_from_subdomain
        provider = self.integration.config.get("provider", "ses")

        if provider == "ses":
            from products.workflows.backend.facade.api import (
                get_ses_email_domain_status,  # noqa: PLC0415 — keeps the workflows facade off the model import path
            )

            return get_ses_email_domain_status(
                domain, mail_from_subdomain=mail_from_subdomain, team_id=self.integration.team_id
            )
        if provider == "maildev":
            from products.workflows.backend.facade.api import (
                get_maildev_email_domain_status,  # noqa: PLC0415 — keeps the workflows facade off the model import path
            )

            return get_maildev_email_domain_status(domain, mail_from_subdomain=mail_from_subdomain)
        raise ValueError(f"Invalid provider: {provider}")

    def _mark_domain_verified(self, on_domain_verified: Callable[[], None] | None) -> None:
        with transaction.atomic():
            senders = list(
                model.Integration.objects.select_for_update()
                .filter(
                    team_id=self.integration.team_id,
                    kind="email",
                    config__domain=self.integration.config.get("domain"),
                    config__provider=self.integration.config.get("provider", "ses"),
                )
                .order_by("id")
            )
            unverified_senders = [sender for sender in senders if not sender.config.get("verified")]
            for sender in unverified_senders:
                sender.config["verified"] = True
                sender.save()

        self.integration.config["verified"] = True

        from products.workflows.backend.facade.api import (
            set_default_email_sender_if_unset,  # noqa: PLC0415 — keeps the workflows facade off the model import path
        )

        set_default_email_sender_if_unset(self.integration.team_id, self.integration.id)

        # A sender added to a domain that is already verified joins it, so only the first verification counts.
        if on_domain_verified and len(unverified_senders) == len(senders):
            on_domain_verified()
        self._after_domain_guard(lambda: self._reload_senders_on_workers(senders))

    # Workers also refresh integrations on their own schedule, so a failed reload only delays sending.
    # Failing the request instead would hide a verification that is already saved.
    def _reload_senders_on_workers(self, senders: list[model.Integration]) -> None:
        try:
            reload_integrations_on_workers(self.integration.team_id, [sender.id for sender in senders])
        except Exception as error:
            capture_exception(error, {"team_id": self.integration.team_id})


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
