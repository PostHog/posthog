"""Native email-sending integration (SES / maildev) and its cleanup signal."""

import json
from collections.abc import Callable, Sequence
from datetime import datetime
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
from posthog.helpers.email_utils import email_domain
from posthog.integrations.contracts import IntegrationConflict, IntegrationPatch, IntegrationRecord
from posthog.integrations.lifecycle import register_delete_hook, sdk_runs_hooks
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.plugins.plugin_server_api import reload_integrations_on_workers

from . import model, row_writes

if TYPE_CHECKING:
    from products.workflows.backend.facade.contracts import EmailDomainCheck, EmailDomainVerification

logger = structlog.get_logger(__name__)

EMAIL_DOMAIN_STATUS_CACHE_SECONDS = 10


def _duplicate_sender_error(email_address: str) -> ValidationError:
    return ValidationError(f"A sender for {email_address} already exists. Edit that sender instead of adding it again.")


def lock_sender_domain(cursor: Any, domain: str) -> None:
    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('email_sender_domain'), hashtext(%s))", [domain])


@frozen
class EmailDomainStatusReport:
    check: "EmailDomainCheck"
    verified: bool
    checked_at: datetime


class EmailIntegration:
    integration: model.Integration

    def __init__(self, integration: IntegrationRecord) -> None:
        if integration.kind != "email":
            raise Exception("EmailIntegration init called with Integration with wrong 'kind'")
        self.integration = model.integration_model(integration)

    @classmethod
    @transaction.atomic
    def create_native_integration(
        cls, config: dict, team_id: int, organization_id: str, created_by: User | None = None
    ) -> IntegrationRecord:
        email_address: str = config["email"].lower()
        name: str = config["name"]
        domain = email_domain(email_address)
        if domain is None:
            raise ValidationError("Enter a valid email address, like hello@example.com.")
        mail_from_subdomain: str = config.get("mail_from_subdomain", "feedback")
        provider: str = config.get("provider", "ses")

        if domain in free_email_domains_list or domain in disposable_email_domains_list:
            raise ValidationError(f"Email domain {domain} is not supported. Please use a custom domain.")

        with connection.cursor() as cursor:
            lock_sender_domain(cursor, domain)

        if row_writes.creator_accessor("email").exists(team_id, external_id=email_address):
            raise _duplicate_sender_error(email_address)

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
            from products.workflows.backend.facade.api import (  # noqa: PLC0415 — keeps the workflows facade off the model import path
                create_ses_email_domain,
                get_ses_mail_from_subdomain,
            )

            domain_in_use = same_domain_integrations.exists()
            if domain_in_use:
                mail_from_subdomain = get_ses_mail_from_subdomain(domain) or mail_from_subdomain

            org_team_ids = list(Team.objects.filter(organization_id=organization_id).values_list("id", flat=True))
            create_ses_email_domain(
                domain,
                mail_from_subdomain=mail_from_subdomain,
                team_id=team_id,
                org_team_ids=org_team_ids,
                keep_existing_mail_from=domain_in_use,
            )
        elif provider == "maildev" and settings.DEBUG:
            pass
        else:
            raise ValueError(f"Invalid provider: must be 'ses'")

        try:
            return row_writes.creator_accessor("email").create(
                team_id,
                external_id=email_address,
                config={
                    "email": email_address,
                    "domain": domain,
                    "mail_from_subdomain": mail_from_subdomain,
                    "reply_to": config.get("reply_to", ""),
                    "name": name,
                    "provider": provider,
                    "verified": True if provider == "maildev" else False,
                },
                created_by_id=created_by.id if created_by else None,
            )
        except IntegrationConflict:
            raise _duplicate_sender_error(email_address)

    def update_native_integration(self, config: dict, team_id: int) -> model.Integration:
        provider = self.integration.config.get("provider")
        domain = self.integration.config.get("domain")
        # Only name, mail_from_subdomain, reply_to and setup_method can be updated
        name: str = config.get("name", self.integration.config.get("name"))
        mail_from_subdomain: str = config.get(
            "mail_from_subdomain", self.integration.config.get("mail_from_subdomain", "feedback")
        )

        mail_from_changed = mail_from_subdomain != self.integration.config.get("mail_from_subdomain", "feedback")

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
        # The SDK merges the patch under a row lock, so a concurrent verification write is kept.
        self.integration = model.integration_model(
            row_writes.update_row(self.integration, IntegrationPatch(config_patch=changes))
        )
        reload_integrations_on_workers(self.integration.team_id, [self.integration.id])

        return self.integration

    def shares_domain_with_other_projects(self) -> bool:
        return (
            model.Integration.objects.filter(kind="email", config__domain=self.integration.config.get("domain"))
            .exclude(team_id=self.integration.team_id)
            .exists()
        )

    def reject_address_change(self, email_address: str) -> None:
        if email_address.lower() != self.integration.config.get("email", "").lower():
            raise ValidationError(f"The sender address cannot change. Create a new sender for {email_address} instead.")

    def _adopt_mail_from_subdomain_ses_uses(self, stored_mail_from_subdomain: str) -> None:
        from products.workflows.backend.facade.api import (
            get_ses_mail_from_subdomain,  # noqa: PLC0415 — keeps the workflows facade off the model import path
        )

        domain = self.integration.config["domain"]
        try:
            ses_mail_from_subdomain = get_ses_mail_from_subdomain(domain)
        except Exception as error:
            capture_exception(error, {"team_id": self.integration.team_id, "domain": domain})
            return
        if not ses_mail_from_subdomain or ses_mail_from_subdomain == stored_mail_from_subdomain:
            return
        with transaction.atomic():
            sender = (
                model.Integration.objects.select_for_update()
                .filter(team_id=self.integration.team_id, id=self.integration.id)
                .first()
            )
            if sender is None or sender.config.get("mail_from_subdomain", "feedback") != stored_mail_from_subdomain:
                return
            sender.config["mail_from_subdomain"] = ses_mail_from_subdomain
            sender.save()
        self.integration = model.integration_model(row_writes.reread_row(self.integration))

    def verify(self, *, on_domain_verified: Callable[[], None] | None = None) -> "EmailDomainVerification":
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
            self._adopt_mail_from_subdomain_ses_uses(mail_from_subdomain)
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
        mail_from_subdomain = self.integration.config.get("mail_from_subdomain", "feedback")
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
        original = self.integration
        senders = row_writes.row_accessor(original).update_where(
            original.team_id,
            where={"domain": original.config.get("domain"), "provider": original.config.get("provider", "ses")},
            patch=IntegrationPatch(config_patch={"verified": True}),
        )
        fresh = next((sender for sender in senders.records if sender.id == original.id), None)
        if fresh is None:
            fresh = row_writes.reread_row(original)
        else:
            row_writes.keep_caller_row_current(original, fresh)
        self.integration = model.integration_model(fresh)

        from products.workflows.backend.facade.api import (
            set_default_email_sender_if_unset,  # noqa: PLC0415 — keeps the workflows facade off the model import path
        )

        set_default_email_sender_if_unset(self.integration.team_id, self.integration.id)

        # A sender added to a domain that is already verified joins it, so only the first verification counts.
        if on_domain_verified and len(senders.changed_ids) == len(senders.records):
            on_domain_verified()
        self._reload_senders_on_workers(senders.records)

    # Workers also refresh integrations on their own schedule, so a failed reload only delays sending.
    # Failing the request instead would hide a verification that is already saved.
    def _reload_senders_on_workers(self, senders: Sequence[IntegrationRecord]) -> None:
        try:
            reload_integrations_on_workers(self.integration.team_id, [sender.id for sender in senders])
        except Exception as error:
            capture_exception(error, {"team_id": self.integration.team_id})


@receiver(models.signals.post_delete, sender=model.Integration)
def clear_default_email_sender_on_integration_delete(sender: Any, instance: model.Integration, **kwargs: Any) -> None:
    # The SDK calls the hook itself. This receiver is for the deletes that do not use the SDK, such as a team delete.
    if not sdk_runs_hooks():
        clear_default_email_sender_of_integration(instance)


def clear_default_email_sender_of_integration(row: IntegrationRecord) -> None:
    if row.kind != "email":
        return

    from products.workflows.backend.facade.api import (
        clear_default_email_sender,  # noqa: PLC0415 — keeps the workflows facade off the model import path
    )

    clear_default_email_sender(row.team_id, row.id)


@receiver(models.signals.post_delete, sender=model.Integration)
def cleanup_ses_identity_on_integration_delete(sender: Any, instance: model.Integration, **kwargs: Any) -> None:
    # A post_delete signal (rather than viewset perform_destroy) so SES identities are
    # also cleaned up when integrations die via cascade, e.g. project or org deletion.
    # Leaving the identity behind permanently blocks the domain for every other
    # organization via the foreign-tenant guard in SESProvider.create_email_domain.
    # The SDK calls the hook itself, so this receiver is only for the deletes that do not use the SDK.
    if not sdk_runs_hooks():
        cleanup_ses_identity_of_integration(instance)


def cleanup_ses_identity_of_integration(row: IntegrationRecord) -> None:
    if row.kind != "email" or row.config.get("provider") != "ses":
        return
    domain = row.config.get("domain")
    if not domain:
        return

    from posthog.tasks.integrations import (
        delete_ses_identity_if_unused,  # noqa: PLC0415 - breaks circular import with the tasks module
    )

    transaction.on_commit(lambda: delete_ses_identity_if_unused.delay(domain))


register_delete_hook(clear_default_email_sender_of_integration)
register_delete_hook(cleanup_ses_identity_of_integration)
