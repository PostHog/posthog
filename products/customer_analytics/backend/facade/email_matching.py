from collections.abc import Iterator
from contextlib import contextmanager
from secrets import randbits

from django.core.cache import cache
from django.db import connections, router, transaction

import structlog
from celery import current_app

from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team
from posthog.models.user import User

from products.conversations.backend.facade import api as conversations
from products.conversations.backend.facade.types import EmailThreadAccountLinkInput, EmailThreadForAccountMatching
from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.logic.account_member_search import is_account_member_search_enabled
from products.customer_analytics.backend.logic.email_account_matching import (
    MatchedAccount,
    match_accounts_for_account_properties,
    match_accounts_for_emails,
    match_accounts_for_gmail_emails,
    normalize_emails,
)
from products.customer_analytics.backend.models import Account

logger = structlog.get_logger(__name__)

_MATCH_SOURCE_PRIORITY = {"known_email": 0, "email_domain": 1, "person_group": 2, "organization_member": 3}
_RECALCULATION_TASK = "customer_analytics.recalculate_email_thread_account_links"
_RECALCULATION_THREADS_TASK = "customer_analytics.recalculate_email_thread_account_links_for_threads"
_RECALCULATION_ACCOUNT_PROPERTIES_TASK = (
    "customer_analytics.recalculate_email_thread_account_links_for_account_properties"
)
_RECALCULATION_LOCK_SECONDS = 15 * 60


def _recalculation_cache_key(team_id: int) -> str:
    return f"customer_analytics:email_thread_link_recalculation:{team_id}"


def _recalculation_dirty_cache_key(team_id: int) -> str:
    return f"customer_analytics:email_thread_link_recalculation_dirty:{team_id}"


def _matching_revision_cache_key(team_id: int) -> str:
    return f"customer_analytics:email_matching_revision:{resolve_effective_team_id(team_id)}"


def _get_matching_revision(team_id: int) -> int | None:
    key = _matching_revision_cache_key(team_id)
    cache.add(key, randbits(63), timeout=None)
    try:
        # Read from the Redis primary so replica lag cannot hide property edits.
        revision = cache.incr(key, delta=0)
    except ValueError:
        return None
    return revision if isinstance(revision, int) else None


@contextmanager
def _guard_email_thread_link_writes(team_id: int) -> Iterator[None]:
    using = router.db_for_write(Account)
    key = f"account-email-links:{resolve_effective_team_id(team_id)}"
    with transaction.atomic(using=using):
        with connections[using].cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [key])
        yield


def finish_email_thread_link_recalculation(team_id: int) -> None:
    cache.delete(_recalculation_cache_key(team_id))
    if cache.delete(_recalculation_dirty_cache_key(team_id)):
        schedule_email_thread_link_recalculation(team_id)


def _enqueue_full_recalculation(team_id: int, cache_key: str) -> None:
    try:
        current_app.send_task(_RECALCULATION_TASK, args=[team_id])
    except Exception:
        cache.delete(cache_key)
        logger.exception("email_thread_link_recalculation_enqueue_failed", team_id=team_id)


def schedule_email_thread_link_recalculation(team_id: int) -> None:
    def enqueue() -> None:
        cache_key = _recalculation_cache_key(team_id)
        if cache.add(cache_key, "1", timeout=_RECALCULATION_LOCK_SECONDS):
            _enqueue_full_recalculation(team_id, cache_key)
            return

        dirty_cache_key = _recalculation_dirty_cache_key(team_id)
        cache.set(dirty_cache_key, "1", timeout=_RECALCULATION_LOCK_SECONDS)
        if cache.add(cache_key, "1", timeout=_RECALCULATION_LOCK_SECONDS):
            cache.delete(dirty_cache_key)
            _enqueue_full_recalculation(team_id, cache_key)

    transaction.on_commit(enqueue)


def schedule_email_thread_link_recalculation_for_threads(team_id: int, thread_ids: list[str]) -> None:
    unique_thread_ids = list(dict.fromkeys(thread_ids))
    if not unique_thread_ids:
        return

    def enqueue() -> None:
        try:
            current_app.send_task(_RECALCULATION_THREADS_TASK, args=[team_id, unique_thread_ids])
        except Exception:
            logger.exception(
                "email_thread_link_recalculation_enqueue_failed",
                team_id=team_id,
                thread_ids=unique_thread_ids,
            )

    transaction.on_commit(enqueue)


def schedule_email_thread_link_recalculation_for_account_properties(
    team_id: int,
    account_id: str,
    *,
    previous_known_emails: list[str],
    previous_email_domains: list[str],
) -> None:
    known_emails = sorted(set(previous_known_emails))
    email_domains = sorted(set(previous_email_domains))

    def enqueue() -> None:
        try:
            cache.set(_matching_revision_cache_key(team_id), randbits(63), timeout=None)
            current_app.send_task(
                _RECALCULATION_ACCOUNT_PROPERTIES_TASK,
                args=[team_id, account_id],
                kwargs={"previous_known_emails": known_emails, "previous_email_domains": email_domains},
            )
        except Exception:
            logger.exception("email_thread_link_recalculation_enqueue_failed", team_id=team_id, account_id=account_id)

    transaction.on_commit(enqueue)


def _dedupe_account_matches(matches_by_email: dict[str, MatchedAccount]) -> list[contracts.EmailAccountMatch]:
    matches_by_account_id: dict[str, contracts.EmailAccountMatch] = {}
    for email in sorted(matches_by_email):
        match = matches_by_email[email]
        account_id = str(match.account.id)
        candidate = contracts.EmailAccountMatch(
            account_id=account_id,
            account_external_id=match.account.external_id,
            match_source=match.source,
        )
        current = matches_by_account_id.get(account_id)
        if (
            current is None
            or _MATCH_SOURCE_PRIORITY[candidate.match_source] < _MATCH_SOURCE_PRIORITY[current.match_source]
        ):
            matches_by_account_id[account_id] = candidate
    return list(matches_by_account_id.values())


def _match_email_accounts(team: Team, emails: list[str]) -> list[contracts.EmailAccountMatch]:
    return _dedupe_account_matches(match_accounts_for_emails(team, emails))


def match_email_accounts(team_id: int, emails: list[str]) -> list[contracts.EmailAccountMatch]:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return []
    return _match_email_accounts(team, emails)


def _create_link_inputs(
    thread: EmailThreadForAccountMatching, matches_by_email: dict[str, MatchedAccount]
) -> list[EmailThreadAccountLinkInput]:
    matches = _dedupe_account_matches(
        {
            email: matches_by_email[email]
            for email in normalize_emails(thread.participant_emails)
            if email in matches_by_email
        }
    )
    return [
        EmailThreadAccountLinkInput(
            account_id=match.account_id,
            account_external_id=match.account_external_id,
            match_source=match.match_source,
        )
        for match in matches
    ]


def _replace_thread_links(
    team_id: int,
    thread: EmailThreadForAccountMatching,
    matches_by_email: dict[str, MatchedAccount],
    *,
    match_sources: list[str] | None = None,
) -> None:
    conversations.replace_email_thread_account_links(
        team_id, thread.id, _create_link_inputs(thread, matches_by_email), match_sources=match_sources
    )


def _create_thread_links(
    team_id: int, thread: EmailThreadForAccountMatching, matches_by_email: dict[str, MatchedAccount]
) -> None:
    conversations.create_email_thread_account_links(team_id, thread.id, _create_link_inputs(thread, matches_by_email))


def recalculate_email_thread_links_for_account_properties(
    team_id: int,
    account_id: str,
    *,
    previous_known_emails: list[str],
    previous_email_domains: list[str],
    batch_size: int = 100,
) -> int:
    account = Account.objects.for_team(team_id).select_related("team").filter(id=account_id).first()
    if account is None:
        return 0

    properties = account.properties
    participant_emails = sorted(set(previous_known_emails) ^ set(properties.known_emails))
    participant_domains = sorted(set(previous_email_domains) ^ set(properties.email_domains))
    if not participant_emails and not participant_domains:
        return 0

    batch_size = max(1, min(batch_size, 500))
    processed = 0
    after_id: str | None = None
    while True:
        threads = conversations.list_email_threads_for_account_matching(
            team_id,
            participant_emails=participant_emails,
            participant_domains=participant_domains,
            after_id=after_id,
            limit=batch_size,
        )
        if not threads:
            return processed

        with _guard_email_thread_link_writes(team_id):
            locked_account = (
                Account.objects.for_team(team_id).select_for_update().only("id").filter(id=account_id).first()
            )
            if locked_account is None:
                return processed

            matches_by_email = match_accounts_for_account_properties(
                account.team, [email for thread in threads for email in thread.participant_emails]
            )
            for thread in threads:
                _replace_thread_links(team_id, thread, matches_by_email, match_sources=["known_email", "email_domain"])
                processed += 1

        if len(threads) < batch_size:
            return processed
        after_id = threads[-1].id


def recalculate_email_thread_links(
    team_id: int,
    *,
    thread_ids: list[str] | None = None,
    append_only: bool = False,
    batch_size: int = 100,
) -> int:
    write_thread_links = _create_thread_links if append_only else _replace_thread_links
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        return 0

    batch_size = max(1, min(batch_size, 500))
    processed = 0
    after_id: str | None = None
    while True:
        threads = conversations.list_email_threads_for_account_matching(
            team_id,
            thread_ids=thread_ids,
            after_id=after_id,
            limit=batch_size,
        )
        if not threads:
            return processed

        owner_ids = {thread.gmail_owner_id for thread in threads if thread.gmail_owner_id is not None}
        owners_by_id = User.objects.in_bulk(owner_ids)
        enabled_owner_ids = {
            owner_id for owner_id, owner in owners_by_id.items() if is_account_member_search_enabled(team, owner)
        }
        threads_by_member_search: dict[bool, list[EmailThreadForAccountMatching]] = {}
        for thread in threads:
            member_search_enabled = thread.gmail_owner_id in enabled_owner_ids
            threads_by_member_search.setdefault(member_search_enabled, []).append(thread)
        matching_revision = _get_matching_revision(team_id)
        matches_by_member_search = {
            member_search_enabled: (
                match_accounts_for_gmail_emails if member_search_enabled else match_accounts_for_emails
            )(team, [email for thread in matching_threads for email in thread.participant_emails])
            for member_search_enabled, matching_threads in threads_by_member_search.items()
        }
        with _guard_email_thread_link_writes(team_id):
            if matching_revision is None or _get_matching_revision(team_id) != matching_revision:
                matches_by_member_search = {
                    member_search_enabled: match_accounts_for_account_properties(
                        team,
                        [email for thread in matching_threads for email in thread.participant_emails],
                        existing_matches=matches_by_member_search[member_search_enabled],
                    )
                    for member_search_enabled, matching_threads in threads_by_member_search.items()
                }
            for thread in threads:
                group_matches = matches_by_member_search[thread.gmail_owner_id in enabled_owner_ids]
                write_thread_links(team_id, thread, group_matches)
                processed += 1

        if len(threads) < batch_size:
            return processed
        after_id = threads[-1].id
