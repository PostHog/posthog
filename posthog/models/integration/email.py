"""Native email-sending integration (SES / maildev) and its cleanup signal."""

import json
import secrets
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
from posthog.integrations.contracts import (
    IntegrationConflict,
    IntegrationNotFound,
    IntegrationPatch,
    IntegrationRecord,
    UpdatedRows,
)
from posthog.integrations.lifecycle import register_delete_hook, sdk_runs_hooks
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.plugins.plugin_server_api import reload_integrations_on_workers

from . import model, row_writes

if TYPE_CHECKING:
    from products.workflows.backend.facade.contracts import (
        EmailDomainCheck,
        EmailDomainDnsRecord,
        EmailDomainVerification,
    )

logger = structlog.get_logger(__name__)

EMAIL_DOMAIN_STATUS_CACHE_SECONDS = 10

# Each domain still waiting for verification holds an identity at the email provider, and the provider
# caps identities per region for all customers together.
MAX_UNVERIFIED_EMAIL_DOMAINS_PER_ORGANIZATION = 3

ORGANIZATION_PROOF_TOKEN_KEY = "organization_proof_token"


def _duplicate_sender_error(email_address: str) -> ValidationError:
    return ValidationError(f"A sender for {email_address} already exists. Edit that sender instead of adding it again.")


def lock_sender_domain(cursor: Any, domain: str) -> None:
    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('email_sender_domain'), hashtext(%s))", [domain])


def lock_organization_sender_domains(cursor: Any, organization_id: str) -> None:
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtext('email_organization_domains'), hashtext(%s))", [organization_id]
    )


def _refuse_another_unverified_domain(organization_id: str) -> None:
    senders = model.Integration.objects.filter(kind="email", team__organization_id=organization_id).values_list(
        "config__domain", "config__verified"
    )
    # A sender added in a second project starts unverified, even when the first project verified its domain.
    verified_domains = {domain for domain, verified in senders if verified is True}
    unverified_domains = {domain for domain, verified in senders if verified is not True} - verified_domains
    if len(unverified_domains) >= MAX_UNVERIFIED_EMAIL_DOMAINS_PER_ORGANIZATION:
        raise ValidationError(
            f"Your organization has {len(unverified_domains)} email domains waiting for verification. "
            "Verify or remove one of them before you add another domain."
        )


def _senders_of_other_organizations(domain: str, organization_id: str) -> list[model.Integration]:
    return list(
        model.Integration.objects.filter(kind="email", config__domain=domain).exclude(
            team__organization_id=organization_id
        )
    )


def _organization_proof_token_for(domain: str, organization_id: str) -> str:
    """The token of the organization's existing senders on the domain, so its projects share one record."""
    existing = (
        model.Integration.objects.filter(
            kind="email",
            config__domain=domain,
            team__organization_id=organization_id,
            config__has_key=ORGANIZATION_PROOF_TOKEN_KEY,
        )
        .values_list(f"config__{ORGANIZATION_PROOF_TOKEN_KEY}", flat=True)
        .first()
    )
    return existing or secrets.token_hex(16)


def _proof_record(domain: str, token: str) -> "EmailDomainDnsRecord":
    from products.workflows.backend.facade.api import (
        email_domain_organization_proof_record,  # noqa: PLC0415 — keeps the workflows facade off the model import path
    )

    return email_domain_organization_proof_record(domain, token=token)


def _proof_published(domain: str, token: str) -> bool:
    from products.workflows.backend.facade.api import (
        email_domain_organization_proof_published,  # noqa: PLC0415 — keeps the workflows facade off the model import path
    )

    return email_domain_organization_proof_published(domain, token=token)


def _release_claims(domain: str, claimants: Sequence[model.Integration]) -> None:
    """End the claims of the other organizations, which could not publish the verifying organization's record."""
    for claimant in claimants:
        try:
            row_writes.row_accessor(claimant).delete(claimant.team_id, claimant.id, ignore_usages=True)
        except IntegrationNotFound:
            continue
    from products.workflows.backend.facade.api import (
        remove_ses_tenant_associations,  # noqa: PLC0415 — keeps the workflows facade off the model import path
    )

    # The domain identity stays for the verifying organization, so the delete hook keeps it and its links to the
    # other organizations' tenants. Those links would make the identity look foreign to the verifying organization.
    remove_ses_tenant_associations(
        domain, team_ids={claimant.team_id for claimant in claimants if claimant.config.get("provider") == "ses"}
    )


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
            # Every create takes it, so a sender deleted meanwhile cannot let a new domain past the cap.
            lock_organization_sender_domains(cursor, str(organization_id))

        if row_writes.creator_accessor("email").exists(team_id, external_id=email_address):
            raise _duplicate_sender_error(email_address)

        same_domain_integrations = model.Integration.objects.filter(kind="email", config__domain=domain)
        other_organization_senders = _senders_of_other_organizations(domain, str(organization_id))
        # Another organization's unverified claim does not block the domain. Each claimant then has to publish its
        # own record to verify it, so a claim made without access to the domain's DNS never verifies.
        if any(sender.config.get("verified") is True for sender in other_organization_senders):
            raise ValidationError(
                f"An email integration with domain {domain} already exists in another organization. Try a different domain or contact support if you believe this is a mistake."
            )

        if not same_domain_integrations.exclude(id__in=[sender.id for sender in other_organization_senders]).exists():
            _refuse_another_unverified_domain(str(organization_id))

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
                unverified_claimant_team_ids=[sender.team_id for sender in other_organization_senders],
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
                    ORGANIZATION_PROOF_TOKEN_KEY: _organization_proof_token_for(domain, str(organization_id)),
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

        if provider not in ("ses", "maildev") or (provider == "maildev" and not settings.DEBUG):
            raise ValueError(f"Invalid provider: must be 'ses'")

        if mail_from_changed:
            # The identity at the provider is shared by every organization that added the domain, so a claim that has
            # not proven ownership must not change it for the others. Under the domain lock, a verification that
            # releases this claim either finishes before the check or waits until the change is made.
            with transaction.atomic():
                with connection.cursor() as cursor:
                    lock_sender_domain(cursor, domain)
                verified = row_writes.reread_row(self.integration).config.get("verified")
                if not verified and self._other_organization_senders():
                    raise ValidationError(
                        "Another organization also added this domain. Verify the domain before you change its MAIL FROM subdomain."
                    )
                if provider == "ses":
                    from products.workflows.backend.facade.api import (
                        update_ses_mail_from_subdomain,  # noqa: PLC0415 — keeps the workflows facade off the model import path
                    )

                    update_ses_mail_from_subdomain(domain, mail_from_subdomain=mail_from_subdomain)

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

        if verification_result.get("status") != "success":
            return verification_result

        # Under the domain lock, a claim added by another organization either commits before this check or waits
        # until this verification is recorded, so two organizations cannot each release the other's claim.
        with transaction.atomic():
            with connection.cursor() as cursor:
                lock_sender_domain(cursor, domain)
            if claimants := self._other_organization_senders():
                proof_token = self._organization_proof_token()
                if any(claimant.config.get("verified") is True for claimant in claimants) or not _proof_published(
                    domain, proof_token
                ):
                    return {
                        "status": "pending",
                        "dnsRecords": [*verification_result["dnsRecords"], _proof_record(domain, proof_token)],
                    }
                _release_claims(domain, claimants)
            senders = self._record_verification()
        self._announce_verification(senders, on_domain_verified)
        return verification_result

    def _organization_id(self) -> str:
        return str(Team.objects.only("organization_id").get(id=self.integration.team_id).organization_id)

    def _other_organization_senders(self) -> list[model.Integration]:
        return _senders_of_other_organizations(self.integration.config["domain"], self._organization_id())

    def _organization_proof_token(self) -> str:
        if token := self.integration.config.get(ORGANIZATION_PROOF_TOKEN_KEY):
            return token
        # Senders added before the record existed have no token, so the first contested check stores one. The domain
        # lock and the reread make two checks that start together store one token, not one each.
        domain = self.integration.config["domain"]
        with transaction.atomic():
            with connection.cursor() as cursor:
                lock_sender_domain(cursor, domain)
            current = row_writes.reread_row(self.integration)
            if not (token := current.config.get(ORGANIZATION_PROOF_TOKEN_KEY)):
                token = _organization_proof_token_for(domain, self._organization_id())
                current = row_writes.update_row(
                    current, IntegrationPatch(config_patch={ORGANIZATION_PROOF_TOKEN_KEY: token})
                )
        self.integration = model.integration_model(current)
        return token

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
        if self._other_organization_senders():
            from products.workflows.backend.facade.api import (  # noqa: PLC0415 — keeps the workflows facade off the model import path
                email_domain_check_with_organization_proof,
            )

            check = email_domain_check_with_organization_proof(
                check, domain=self.integration.config["domain"], token=self._organization_proof_token()
            )
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

    def _record_verification(self) -> UpdatedRows:
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
        return senders

    def _announce_verification(self, senders: UpdatedRows, on_domain_verified: Callable[[], None] | None) -> None:
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
