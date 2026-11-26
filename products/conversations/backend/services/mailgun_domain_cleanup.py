"""Remove Mailgun sending domains that this region registered and no live support email setup uses.

A domain goes when no support channel references it, or when every channel on it is an abandoned setup that
never verified. The channels of an abandoned setup stay, and verifying again registers the domain again.
"""

from __future__ import annotations

import time
import random
from collections import Counter
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

from django.contrib.postgres.aggregates import BoolOr
from django.db.models import Max
from django.db.models.functions import Lower
from django.utils import timezone

import requests
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
# Both the newest channel and the Mailgun registration must be this old, so a verify that registers an
# expired domain again starts a new period.
ABANDONED_SETUP_AGE = timedelta(days=90)
MAX_DELETIONS_PER_RUN = 100
MAX_PRUNE_CHECKS_PER_RUN = 100
DELETE_PAUSE_SECONDS = 0.1


@frozen
class OrphanScan:
    owned: dict[str, str]
    abandoned: dict[str, str]
    unowned: list[str]
    kept: Counter[str]


@frozen
class CleanupResult:
    mailgun_domain_count: int
    candidates: list[str]
    abandoned_setups: list[str]
    unowned_orphans: list[str]
    kept: dict[str, int]
    adopted_registrations: int
    deleted: int
    failed: int
    pruned_registrations: int
    throttled: bool


class _MailgunThrottled(Exception):
    pass


def _raise_if_throttled(error: Exception) -> None:
    if isinstance(error, requests.HTTPError) and error.response is not None and error.response.status_code == 429:
        raise _MailgunThrottled from error


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


def _abandoned_setup_domains(cutoff: datetime, domain: str | None = None) -> set[str]:
    """Support domains where no channel ever verified and the newest channel is older than the cutoff."""
    channels = EmailChannel.objects.filter(kind=EmailChannelKind.SUPPORT)
    if domain is not None:
        channels = channels.filter(domain__iexact=domain)
    return set(
        channels.annotate(name=Lower("domain"))
        .values("name")
        .annotate(any_verified=BoolOr("domain_verified"), newest=Max("created_at"))
        .filter(any_verified=False, newest__lt=cutoff)
        .order_by()
        .values_list("name", flat=True)
    )


def _scan_orphans(mailgun_domains: list[dict[str, Any]], now: datetime, adopted: dict[str, str]) -> OrphanScan:
    protected: set[str] = set()
    inbound_domain = get_instance_setting("CONVERSATIONS_EMAIL_INBOUND_DOMAIN")
    if inbound_domain:
        protected.add(inbound_domain.lower())

    support_domains = {
        domain.lower()
        for domain in EmailChannel.objects.filter(kind=EmailChannelKind.SUPPORT).values_list("domain", flat=True)
    }
    abandoned_cutoff = now - ABANDONED_SETUP_AGE
    abandoned_domains = _abandoned_setup_domains(abandoned_cutoff)
    registered_ids = dict(
        MailgunDomainRegistration.objects.exclude(mailgun_domain_id="").values_list("domain", "mailgun_domain_id")
    )
    registered_ids.update(adopted)
    scan = OrphanScan(owned={}, abandoned={}, unowned=[], kept=Counter())

    for item in mailgun_domains:
        name = str(item.get("name", "")).lower()
        state = str(item.get("state", ""))
        created_at = _mailgun_created_at(item)
        owned = bool(registered_ids.get(name)) and registered_ids.get(name) == item.get("id")
        if not name or name in protected:
            scan.kept["protected"] += 1
        elif name in support_domains:
            if (
                name in abandoned_domains
                and state == "unverified"
                and created_at is not None
                and created_at < abandoned_cutoff
            ):
                if owned:
                    scan.abandoned[name] = registered_ids[name]
                else:
                    scan.kept["abandoned_setup_unowned"] += 1
            else:
                scan.kept["in_use"] += 1
        elif created_at is None or created_at > now - ORPHAN_MIN_AGE:
            scan.kept["orphan_too_new"] += 1
        elif state != "unverified":
            # An active or disabled orphan may belong to something outside Conversations. Operators decide.
            scan.kept[f"orphan_{state or 'unknown'}"] += 1
        elif owned:
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
    for registration_id, domain, registered_id, registered_at in random.sample(
        suspects, min(len(suspects), MAX_PRUNE_CHECKS_PER_RUN)
    ):
        try:
            current = get_domain(domain)
        except Exception as error:
            _raise_if_throttled(error)
            logger.exception("mailgun_domain_cleanup_prune_lookup_failed", domain=domain)
            continue
        if _registration_gone(registered_id, current):
            deleted, _ = MailgunDomainRegistration.objects.filter(
                id=registration_id, registered_at=registered_at
            ).delete()
            pruned += deleted
    return pruned


def _delete_if_unchanged(domain: str, mailgun_domain_id: str, reason: str, kept: Counter[str]) -> bool | None:
    """Delete the domain only if Mailgun still holds the same unverified registration. None means it failed."""
    try:
        current = get_domain(domain)
        if current is None or current.get("id") != mailgun_domain_id or current.get("state") != "unverified":
            kept["changed_during_run"] += 1
            return False
        delete_domain(domain)
        logger.info("mailgun_domain_cleanup_deleted", domain=domain, reason=reason)
        return True
    except Exception as error:
        _raise_if_throttled(error)
        logger.exception("mailgun_domain_cleanup_delete_failed", domain=domain, reason=reason)
        return None
    finally:
        time.sleep(DELETE_PAUSE_SECONDS)


def cleanup_mailgun_domains(*, dry_run: bool, max_deletions: int = MAX_DELETIONS_PER_RUN) -> CleanupResult:
    now = timezone.now()
    mailgun_domains = list_domains()
    adoptable = _adoptable_registrations(mailgun_domains)
    scan = _scan_orphans(mailgun_domains, now, adoptable)
    # A random batch, so domains that fail every run cannot hold back the rest.
    candidates = random.sample(list(scan.owned), min(len(scan.owned), max_deletions))
    abandoned_setups = random.sample(list(scan.abandoned), min(len(scan.abandoned), max_deletions - len(candidates)))
    kept = scan.kept

    deleted = 0
    failed = 0
    pruned = 0
    adopted = 0
    throttled = False
    outcomes: list[bool | None] = []
    if not dry_run:
        for domain, mailgun_domain_id in adoptable.items():
            adopted += MailgunDomainRegistration.objects.filter(domain=domain, mailgun_domain_id="").update(
                mailgun_domain_id=mailgun_domain_id
            )
        try:
            pruned = _prune_registrations(mailgun_domains, now)
            for domain in candidates:
                # A connect may have saved a channel for this domain since the snapshot.
                if EmailChannel.objects.filter(domain__iexact=domain, kind=EmailChannelKind.SUPPORT).exists():
                    kept["claimed_during_run"] += 1
                    continue
                outcomes.append(_delete_if_unchanged(domain, scan.owned[domain], "orphan", kept))
            for domain in abandoned_setups:
                # A channel may have verified, or a new channel may have joined the domain, since the snapshot.
                if domain not in _abandoned_setup_domains(now - ABANDONED_SETUP_AGE, domain):
                    kept["setup_resumed_during_run"] += 1
                    continue
                outcomes.append(_delete_if_unchanged(domain, scan.abandoned[domain], "abandoned_setup", kept))
        except _MailgunThrottled:
            # The account is shared with live email setup, so leave the rest of the batch to the next run.
            throttled = True
            logger.warning("mailgun_domain_cleanup_throttled")
        deleted = outcomes.count(True)
        failed = outcomes.count(None)

    return CleanupResult(
        mailgun_domain_count=len(mailgun_domains),
        candidates=candidates,
        abandoned_setups=abandoned_setups,
        unowned_orphans=scan.unowned,
        kept=dict(kept),
        adopted_registrations=adopted,
        deleted=deleted,
        failed=failed,
        pruned_registrations=pruned,
        throttled=throttled,
    )
