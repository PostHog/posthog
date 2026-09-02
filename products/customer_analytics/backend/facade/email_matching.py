from django.core.cache import cache
from django.db import transaction

import structlog
from celery import current_app

from posthog.models.team import Team

from products.conversations.backend.facade import api as conversations
from products.conversations.backend.facade.types import EmailThreadAccountLinkInput
from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.logic.email_account_matching import (
    MatchedAccount,
    match_accounts_for_emails,
    normalize_emails,
)

logger = structlog.get_logger(__name__)

_MATCH_SOURCE_PRIORITY = {"known_email": 0, "person_group": 1, "email_domain": 2}
_RECALCULATION_TASK = "customer_analytics.recalculate_email_thread_account_links"
_RECALCULATION_THREADS_TASK = "customer_analytics.recalculate_email_thread_account_links_for_threads"
_RECALCULATION_LOCK_SECONDS = 15 * 60


def _recalculation_cache_key(team_id: int) -> str:
    return f"customer_analytics:email_thread_link_recalculation:{team_id}"


def _recalculation_dirty_cache_key(team_id: int) -> str:
    return f"customer_analytics:email_thread_link_recalculation_dirty:{team_id}"


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


def recalculate_email_thread_links(
    team_id: int,
    *,
    thread_ids: list[str] | None = None,
    batch_size: int = 100,
) -> int:
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

        # One matcher pass per page, not per thread: participants and domains that recur
        # across a customer's threads collapse into a single set of queries.
        page_matches = match_accounts_for_emails(
            team, [email for thread in threads for email in thread.participant_emails]
        )
        for thread in threads:
            thread_matches = {
                email: page_matches[email]
                for email in normalize_emails(thread.participant_emails)
                if email in page_matches
            }
            matches = _dedupe_account_matches(thread_matches)
            conversations.replace_email_thread_account_links(
                team_id,
                thread.id,
                [
                    EmailThreadAccountLinkInput(
                        account_id=match.account_id,
                        account_external_id=match.account_external_id,
                        match_source=match.match_source,
                    )
                    for match in matches
                ],
            )
            processed += 1

        if len(threads) < batch_size:
            return processed
        after_id = threads[-1].id
