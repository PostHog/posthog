"""Remove Mailgun sending domains that this region registered and no support email channel references."""

from __future__ import annotations

import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.instance_setting import get_instance_setting

from products.conversations.backend.mailgun import delete_domain, list_domains
from products.conversations.backend.models import EmailChannel, EmailChannelKind, MailgunDomainRegistration

logger = structlog.get_logger(__name__)

# An orphan this young may belong to a connect that registered the domain but has not saved its channel yet.
ORPHAN_MIN_AGE = timedelta(hours=1)
# Allows for clock skew between Mailgun and us when comparing creation times.
REGISTRATION_CLOCK_SKEW = timedelta(minutes=10)
MAX_DELETIONS_PER_RUN = 100
DELETE_PAUSE_SECONDS = 0.1


@frozen
class OrphanScan:
    owned: list[str]
    # Orphans this region did not register. Another region may still use them, so only an operator can delete them.
    unowned: list[str]
    kept: Counter[str]


@frozen
class CleanupResult:
    mailgun_domain_count: int
    candidates: list[str]
    unowned_orphans: list[str]
    kept: dict[str, int]
    deleted: int
    failed: int
    pruned_registrations: int


def _mailgun_created_at(item: dict[str, Any]) -> datetime | None:
    raw = item.get("created_at")
    if not isinstance(raw, str):
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    # parsedate_to_datetime returns a naive datetime for a "-0000" offset, which cannot be compared with now.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _scan_orphans(mailgun_domains: list[dict[str, Any]], now: datetime) -> OrphanScan:
    protected: set[str] = set()
    inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN")
    if inbound_domain:
        protected.add(inbound_domain.lower())

    support_domains = {
        domain.lower()
        for domain in EmailChannel.objects.filter(kind=EmailChannelKind.SUPPORT).values_list("domain", flat=True)
    }
    registered_at_by_domain = dict(MailgunDomainRegistration.objects.values_list("domain", "registered_at"))
    scan = OrphanScan(owned=[], unowned=[], kept=Counter())

    for item in mailgun_domains:
        name = str(item.get("name", "")).lower()
        state = str(item.get("state", ""))
        created_at = _mailgun_created_at(item)
        if not name or name in protected:
            scan.kept["protected"] += 1
        elif name in support_domains:
            scan.kept["in_use"] += 1
        elif created_at is None or created_at > now - ORPHAN_MIN_AGE:
            scan.kept["orphan_too_new"] += 1
        elif state != "unverified":
            # An active or disabled orphan may belong to something outside Conversations. Operators decide.
            scan.kept[f"orphan_{state or 'unknown'}"] += 1
        else:
            registered_at = registered_at_by_domain.get(name)
            # Another region can reclaim an unverified domain, which re-creates it in Mailgun after our registration.
            if registered_at is None or created_at > registered_at + REGISTRATION_CLOCK_SKEW:
                scan.unowned.append(name)
            else:
                scan.owned.append(name)

    return scan


def _prune_registrations(mailgun_domains: list[dict[str, Any]], now: datetime) -> int:
    """Forget registrations for domains that left Mailgun some other way, such as a manual delete."""
    in_mailgun = {str(item.get("name", "")).lower() for item in mailgun_domains}
    stale_ids = [
        registration_id
        for registration_id, domain in MailgunDomainRegistration.objects.filter(
            registered_at__lt=now - ORPHAN_MIN_AGE
        ).values_list("id", "domain")
        if domain not in in_mailgun
    ]
    deleted, _ = MailgunDomainRegistration.objects.filter(id__in=stale_ids).delete()
    return deleted


def cleanup_mailgun_domains(*, dry_run: bool, max_deletions: int = MAX_DELETIONS_PER_RUN) -> CleanupResult:
    now = timezone.now()
    mailgun_domains = list_domains()
    scan = _scan_orphans(mailgun_domains, now)
    candidates = scan.owned[:max_deletions]
    kept = scan.kept

    deleted = 0
    failed = 0
    pruned = 0
    if not dry_run:
        pruned = _prune_registrations(mailgun_domains, now)
        for domain in candidates:
            # A connect may have saved a channel for this domain since the snapshot.
            if EmailChannel.objects.filter(domain__iexact=domain, kind=EmailChannelKind.SUPPORT).exists():
                kept["claimed_during_run"] += 1
                continue
            try:
                delete_domain(domain)
                deleted += 1
                logger.info("mailgun_domain_cleanup_deleted", domain=domain)
            except Exception:
                failed += 1
                logger.exception("mailgun_domain_cleanup_delete_failed", domain=domain)
            time.sleep(DELETE_PAUSE_SECONDS)

    return CleanupResult(
        mailgun_domain_count=len(mailgun_domains),
        candidates=candidates,
        unowned_orphans=scan.unowned,
        kept=dict(kept),
        deleted=deleted,
        failed=failed,
        pruned_registrations=pruned,
    )
