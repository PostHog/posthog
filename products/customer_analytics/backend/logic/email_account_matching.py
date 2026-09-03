from collections.abc import Callable
from dataclasses import dataclass

from django.db.models import QuerySet
from django.db.models.functions import Lower

import structlog

from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.conversations.backend.facade.api import resolve_group_keys_by_email
from products.customer_analytics.backend.logic.account_member_search import get_account_member_search_staff_user
from products.customer_analytics.backend.models import Account

logger = structlog.get_logger(__name__)

KNOWN_EMAIL_MATCH = "known_email"
PERSON_GROUP_MATCH = "person_group"
ORGANIZATION_MEMBER_MATCH = "organization_member"
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


def _find_accounts_by_known_email(team: Team, email: str) -> QuerySet[Account]:
    return Account.objects.for_team(team.id).filter(_properties__known_emails__contains=[email])


def _find_accounts_by_email_domain(team: Team, domain: str) -> QuerySet[Account]:
    return Account.objects.for_team(team.id).filter(_properties__email_domains__contains=[domain])


def _match_accounts_by_account_property(
    team: Team,
    emails: list[str],
    *,
    find_accounts: Callable[[Team, str], QuerySet[Account]],
    source: str,
    value_for_email: Callable[[str], str],
) -> tuple[dict[str, MatchedAccount], set[str]]:
    matches: dict[str, MatchedAccount] = {}
    ambiguous: set[str] = set()
    for email in emails:
        value = value_for_email(email)
        candidates = list(find_accounts(team, value)[:2])
        if len(candidates) == 1:
            matches[email] = MatchedAccount(account=candidates[0], source=source)
        elif len(candidates) > 1:
            ambiguous.add(email)
            _record_ambiguity(team_id=team.id, source=source, candidate_count=len(candidates))
    return matches, ambiguous


def _match_accounts_by_person_group(team: Team, emails: list[str]) -> tuple[dict[str, MatchedAccount], set[str]]:
    group_type_index = team.customer_analytics_config.account_group_type_index
    if group_type_index is None:
        return {}, set()

    matches: dict[str, MatchedAccount] = {}
    ambiguous: set[str] = set()
    email_to_group_key = resolve_group_keys_by_email(team.id, emails, group_type_index)
    group_keys = {group_key for group_key in email_to_group_key.values() if group_key is not None}
    accounts_by_external_id = {
        account.external_id: account for account in Account.objects.for_team(team.id).filter(external_id__in=group_keys)
    }
    for email, group_key in email_to_group_key.items():
        if group_key is None:
            ambiguous.add(email)
            _record_ambiguity(team_id=team.id, source=PERSON_GROUP_MATCH, candidate_count=None)
            continue
        account = accounts_by_external_id.get(group_key)
        if account is not None:
            matches[email] = MatchedAccount(account=account, source=PERSON_GROUP_MATCH)
    return matches, ambiguous


def _match_accounts_by_organization_membership(
    team: Team, emails: list[str]
) -> tuple[dict[str, MatchedAccount], set[str]]:
    if get_account_member_search_staff_user(team) is None:
        return {}, set()

    users_by_email: dict[str, list[User]] = {}
    for user in (
        User.objects.annotate(normalized_email=Lower("email"))
        .filter(normalized_email__in=emails, is_active=True)
        .only("id", "email")
    ):
        users_by_email.setdefault(user.email.lower(), []).append(user)

    ambiguous = {email for email, users in users_by_email.items() if len(users) > 1}
    users_by_id = {users[0].id: users[0] for email, users in users_by_email.items() if email not in ambiguous}
    if not users_by_id:
        return {}, ambiguous

    memberships = list(OrganizationMembership.objects.filter(user_id__in=users_by_id))
    accounts_by_organization_id = {
        account.external_id: account
        for account in Account.objects.for_team(team.id).filter(
            external_id__in={str(membership.organization_id) for membership in memberships}
        )
        if account.external_id is not None
    }

    candidates_by_email: dict[str, dict[str, Account]] = {}
    for membership in memberships:
        account = accounts_by_organization_id.get(str(membership.organization_id))
        if account is None:
            continue
        email = users_by_id[membership.user_id].email.lower()
        candidates_by_email.setdefault(email, {})[str(account.id)] = account

    matches: dict[str, MatchedAccount] = {}
    for email, candidates in candidates_by_email.items():
        if len(candidates) == 1:
            matches[email] = MatchedAccount(account=next(iter(candidates.values())), source=ORGANIZATION_MEMBER_MATCH)
        else:
            ambiguous.add(email)
            _record_ambiguity(team_id=team.id, source=ORGANIZATION_MEMBER_MATCH, candidate_count=None)
    return matches, ambiguous


def _unresolved_emails(emails: list[str], matched: dict[str, MatchedAccount], ambiguous: set[str]) -> list[str]:
    return [email for email in emails if email not in matched and email not in ambiguous]


def match_accounts_for_emails(team: Team, emails: list[str]) -> dict[str, MatchedAccount]:
    normalized_emails = sorted(normalize_emails(emails))
    if not normalized_emails:
        return {}

    matched, ambiguous = _match_accounts_by_account_property(
        team,
        normalized_emails,
        find_accounts=_find_accounts_by_known_email,
        source=KNOWN_EMAIL_MATCH,
        value_for_email=lambda email: email,
    )
    person_group_matches, person_group_ambiguous = _match_accounts_by_person_group(
        team,
        _unresolved_emails(normalized_emails, matched, ambiguous),
    )
    matched.update(person_group_matches)
    ambiguous.update(person_group_ambiguous)

    organization_matches, organization_ambiguous = _match_accounts_by_organization_membership(
        team,
        _unresolved_emails(normalized_emails, matched, ambiguous),
    )
    matched.update(organization_matches)
    ambiguous.update(organization_ambiguous)

    domain_matches, _ = _match_accounts_by_account_property(
        team,
        _unresolved_emails(normalized_emails, matched, ambiguous),
        find_accounts=_find_accounts_by_email_domain,
        source=EMAIL_DOMAIN_MATCH,
        value_for_email=lambda email: email.rsplit("@", 1)[-1],
    )
    matched.update(domain_matches)
    return matched
