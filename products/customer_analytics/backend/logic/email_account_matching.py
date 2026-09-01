from dataclasses import dataclass

import structlog

from posthog.models.team import Team

from products.conversations.backend.facade.api import resolve_group_keys_by_email
from products.customer_analytics.backend.models import Account

logger = structlog.get_logger(__name__)

KNOWN_EMAIL_MATCH = "known_email"
PERSON_GROUP_MATCH = "person_group"
EMAIL_DOMAIN_MATCH = "email_domain"


@dataclass(frozen=True, kw_only=True)
class MatchedAccount:
    account: Account
    source: str


def _record_ambiguity(*, team_id: int, source: str, candidate_count: int | None) -> None:
    logger.warning(
        "email_account_match_ambiguous",
        team_id=team_id,
        match_source=source,
        candidate_count=candidate_count,
    )


def normalize_emails(emails: list[str]) -> set[str]:
    return {email.strip().lower() for email in emails if "@" in email}


def match_accounts_for_emails(team: Team, emails: list[str]) -> dict[str, MatchedAccount]:
    normalized_emails = sorted(normalize_emails(emails))
    if not normalized_emails:
        return {}

    matched: dict[str, MatchedAccount] = {}
    ambiguous: set[str] = set()

    for email in normalized_emails:
        candidates = list(Account.objects.for_team(team.id).filter(_properties__known_emails__contains=[email])[:2])
        if len(candidates) == 1:
            matched[email] = MatchedAccount(account=candidates[0], source=KNOWN_EMAIL_MATCH)
        elif len(candidates) > 1:
            ambiguous.add(email)
            _record_ambiguity(team_id=team.id, source=KNOWN_EMAIL_MATCH, candidate_count=len(candidates))

    group_type_index = team.customer_analytics_config.account_group_type_index
    if group_type_index is not None:
        unresolved = [email for email in normalized_emails if email not in matched and email not in ambiguous]
        email_to_group_key = resolve_group_keys_by_email(team.id, unresolved, group_type_index)
        group_keys = {group_key for group_key in email_to_group_key.values() if group_key is not None}
        accounts_by_external_id = {
            account.external_id: account
            for account in Account.objects.for_team(team.id).filter(external_id__in=group_keys)
        }
        for email, group_key in email_to_group_key.items():
            if group_key is None:
                ambiguous.add(email)
                _record_ambiguity(team_id=team.id, source=PERSON_GROUP_MATCH, candidate_count=None)
                continue
            account = accounts_by_external_id.get(group_key)
            if account is not None:
                matched[email] = MatchedAccount(account=account, source=PERSON_GROUP_MATCH)

    for email in normalized_emails:
        if email in matched or email in ambiguous:
            continue
        domain = email.rsplit("@", 1)[-1]
        candidates = list(Account.objects.for_team(team.id).filter(_properties__email_domains__contains=[domain])[:2])
        if len(candidates) == 1:
            matched[email] = MatchedAccount(account=candidates[0], source=EMAIL_DOMAIN_MATCH)
        elif len(candidates) > 1:
            _record_ambiguity(team_id=team.id, source=EMAIL_DOMAIN_MATCH, candidate_count=len(candidates))

    return matched
