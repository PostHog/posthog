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

from products.conversations.backend.mailgun import delete_domain, get_domain, list_domains
from products.conversations.backend.models import EmailChannel, EmailChannelKind, MailgunDomainRegistration

logger = structlog.get_logger(__name__)

# An orphan this young may belong to a connect that registered the domain but has not saved its channel yet.
ORPHAN_MIN_AGE = timedelta(hours=1)
# Connect registers the domain moments before it saves the first channel. A backfilled row only adopts
# a Mailgun registration created this close to its first channel, so a later reclaim stays unowned.
BACKFILL_MATCH_WINDOW = timedelta(minutes=10)
MAX_DELETIONS_PER_RUN = 100
MAX_PRUNE_CHECKS_PER_RUN = 100
DELETE_PAUSE_SECONDS = 0.1


@frozen
class OrphanScan:
    owned: dict[str, str]
    unowned: list[str]
    kept: Counter[str]


@frozen
class CleanupResult:
    mailgun_domain_count: int
    candidates: list[str]
    unowned_orphans: list[str]
    kept: dict[str, int]
    adopted_registrations: int
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


def _adoptable_registrations(mailgun_domains: list[dict[str, Any]]) -> dict[str, str]:
    """Match backfilled rows, which have no Mailgun id yet, to the Mailgun registration they describe."""
    first_channel_at = dict(
        MailgunDomainRegistration.objects.filter(mailgun_domain_id="").values_list("domain", "registered_at")
    )
    adoptable: dict[str, str] = {}
    for item in mailgun_domains:
        name = str(item.get("name", "")).lower()
        mailgun_domain_id = item.get("id")
        created_at = _mailgun_created_at(item)
        if (
            name in first_channel_at
            and isinstance(mailgun_domain_id, str)
            and mailgun_domain_id
            and created_at is not None
            and abs(created_at - first_channel_at[name]) <= BACKFILL_MATCH_WINDOW
        ):
            adoptable[name] = mailgun_domain_id
    return adoptable


def _scan_orphans(mailgun_domains: list[dict[str, Any]], now: datetime, adopted: dict[str, str]) -> OrphanScan:
    protected: set[str] = set()
    inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN")
    if inbound_domain:
        protected.add(inbound_domain.lower())

    support_domains = {
        domain.lower()
        for domain in EmailChannel.objects.filter(kind=EmailChannelKind.SUPPORT).values_list("domain", flat=True)
    }
    registered_ids = dict(
        MailgunDomainRegistration.objects.exclude(mailgun_domain_id="").values_list("domain", "mailgun_domain_id")
    )
    registered_ids.update(adopted)
    scan = OrphanScan(owned={}, unowned=[], kept=Counter())

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
        elif registered_ids.get(name) and registered_ids[name] == item.get("id"):
            scan.owned[name] = registered_ids[name]
        else:
            # Another region registered or reclaimed it and may still use it, so only an operator can delete it.
            scan.unowned.append(name)

    return scan


def _registration_gone(registered_id: str, current: dict[str, Any] | None) -> bool:
    return current is None or bool(registered_id and current.get("id") != registered_id)


def _prune_registrations(mailgun_domains: list[dict[str, Any]], now: datetime) -> int:
    """Forget registrations that left Mailgun some other way, such as a manual delete or a reclaim by another region."""
    listed = {str(item.get("name", "")).lower(): item for item in mailgun_domains}
    suspects = [
        (registration_id, domain, registered_id, registered_at)
        for registration_id, domain, registered_id, registered_at in MailgunDomainRegistration.objects.filter(
            registered_at__lt=now - ORPHAN_MIN_AGE
        ).values_list("id", "domain", "mailgun_domain_id", "registered_at")
        if _registration_gone(registered_id, listed.get(domain))
    ]

    pruned = 0
    # The listing pages by offset, so it can skip a domain that another region deletes during the scan.
    for registration_id, domain, registered_id, registered_at in suspects[:MAX_PRUNE_CHECKS_PER_RUN]:
        try:
            current = get_domain(domain)
        except Exception:
            logger.exception("mailgun_domain_cleanup_prune_lookup_failed", domain=domain)
            continue
        if _registration_gone(registered_id, current):
            deleted, _ = MailgunDomainRegistration.objects.filter(
                id=registration_id, registered_at=registered_at
            ).delete()
            pruned += deleted
    return pruned


def cleanup_mailgun_domains(*, dry_run: bool, max_deletions: int = MAX_DELETIONS_PER_RUN) -> CleanupResult:
    now = timezone.now()
    mailgun_domains = list_domains()
    adoptable = _adoptable_registrations(mailgun_domains)
    scan = _scan_orphans(mailgun_domains, now, adoptable)
    candidates = list(scan.owned)[:max_deletions]
    kept = scan.kept

    deleted = 0
    failed = 0
    pruned = 0
    adopted = 0
    if not dry_run:
        for domain, mailgun_domain_id in adoptable.items():
            adopted += MailgunDomainRegistration.objects.filter(domain=domain, mailgun_domain_id="").update(
                mailgun_domain_id=mailgun_domain_id
            )
        pruned = _prune_registrations(mailgun_domains, now)
        for domain in candidates:
            # A connect may have saved a channel for this domain since the snapshot.
            if EmailChannel.objects.filter(domain__iexact=domain, kind=EmailChannelKind.SUPPORT).exists():
                kept["claimed_during_run"] += 1
                continue
            try:
                current = get_domain(domain)
                if current is None or current.get("id") != scan.owned[domain] or current.get("state") != "unverified":
                    kept["changed_during_run"] += 1
                    continue
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
        adopted_registrations=adopted,
        deleted=deleted,
        failed=failed,
        pruned_registrations=pruned,
    )
