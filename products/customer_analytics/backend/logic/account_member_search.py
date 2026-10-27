from typing import cast
from uuid import UUID

from django.core.exceptions import ValidationError

import structlog

from posthog.hogql import ast
from posthog.hogql.errors import ResolutionError, TableAccessDeniedError
from posthog.hogql.query import execute_hogql_query

from posthog.api.organization_member import organization_members_base_queryset
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.constants import INTERNAL_BOT_EMAIL_SUFFIX
from posthog.models import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import posthog_feature_flag_enabled

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.customer_analytics.backend.constants import CUSTOMER_ANALYTICS_CSP_FLAG
from products.customer_analytics.backend.models.account import Account

logger = structlog.get_logger(__name__)

ACCOUNT_MEMBER_SEARCH_MAX_ORGANIZATIONS = 100
# The member list becomes a constant IN list in ClickHouse, which caps how many members one query can carry.
ORGANIZATION_MEMBERS_MAX = 10_000
EU_ORGANIZATION_MEMBERS_VIEW = "eu_org_members"


def is_account_member_search_enabled(team: Team, user: User) -> bool:
    return (
        user.is_active
        and user.is_staff
        and posthog_feature_flag_enabled(
            CUSTOMER_ANALYTICS_CSP_FLAG,
            str(user.distinct_id),
            organization_id=team.organization_id,
            team_id=team.id,
        )
    )


def _list_us_organization_ids(email: str) -> tuple[str, ...]:
    if email.endswith(INTERNAL_BOT_EMAIL_SUFFIX):
        return ()
    organization_ids = (
        OrganizationMembership.objects.filter(user__email=email, user__is_active=True)
        .order_by("organization_id")
        .values_list("organization_id", flat=True)[:ACCOUNT_MEMBER_SEARCH_MAX_ORGANIZATIONS]
    )
    return tuple(str(organization_id) for organization_id in organization_ids)


def _query_eu_organization_members(
    team: Team,
    user: User,
    *,
    query: str,
    placeholders: dict[str, ast.Expr],
    query_type: str,
    log_event: str,
    raise_query_failures: bool = False,
) -> tuple[str, ...]:
    try:
        with tags_context(product=Product.CUSTOMER_ANALYTICS, feature=Feature.QUERY):
            response = execute_hogql_query(
                query=query,
                placeholders=placeholders,
                team=team,
                user=user,
                query_type=query_type,
            )
    except (ResolutionError, TableAccessDeniedError) as error:
        logger.info(f"{log_event}_unavailable", team_id=team.id, error_type=type(error).__name__)
        return ()
    except Exception as error:
        logger.warning(f"{log_event}_failed", team_id=team.id, error_type=type(error).__name__)
        if raise_query_failures:
            raise
        return ()

    rows = cast(list[list[object]], response.results or [])
    return tuple(str(row[0]) for row in rows if row and row[0] is not None)


def _list_eu_organization_ids(team: Team, user: User, email: str) -> tuple[str, ...]:
    return _query_eu_organization_members(
        team,
        user,
        query=f"""
            SELECT DISTINCT organization_id
            FROM {EU_ORGANIZATION_MEMBERS_VIEW}
            WHERE email = {{email}}
            ORDER BY organization_id
            LIMIT {ACCOUNT_MEMBER_SEARCH_MAX_ORGANIZATIONS}
        """,
        placeholders={"email": ast.Constant(value=email)},
        query_type="customer_analytics_account_member_email_lookup",
        log_event="account_member_email_lookup",
    )


def list_account_external_ids_by_member_email(*, team: Team, user: User, email: str) -> tuple[str, ...]:
    if not is_account_member_search_enabled(team, user):
        return ()

    organization_ids = _list_us_organization_ids(email)
    if organization_ids:
        return organization_ids
    return _list_eu_organization_ids(team, user, email)


def list_organization_member_distinct_ids(*, team: Team, user: User, organization_id: str) -> tuple[str, ...]:
    """Distinct IDs of the PostHog Cloud users in an organization, from US Postgres or else the EU warehouse view."""
    us_distinct_ids = tuple(
        organization_members_base_queryset()
        .filter(organization_id=organization_id, user__distinct_id__isnull=False)
        .order_by("-joined_at")
        .values_list("user__distinct_id", flat=True)[:ORGANIZATION_MEMBERS_MAX]
    )
    if us_distinct_ids:
        return us_distinct_ids
    return _query_eu_organization_members(
        team,
        user,
        query=f"""
            SELECT distinct_id
            FROM {EU_ORGANIZATION_MEMBERS_VIEW}
            WHERE organization_id = {{organization_id}} AND distinct_id IS NOT NULL
            ORDER BY joined_at DESC
            LIMIT {ORGANIZATION_MEMBERS_MAX}
        """,
        placeholders={"organization_id": ast.Constant(value=organization_id)},
        query_type="customer_analytics_account_member_distinct_id_lookup",
        log_event="account_member_distinct_id_lookup",
        raise_query_failures=True,
    )


def get_account_users_organization_id(*, team: Team, user: User | None, account_id: str) -> str | None:
    """The PostHog Cloud organization behind an account's users, or None when the account has none.

    Raises `UserAccessControlError` unless `user` is flagged staff who can see the account: members are
    read from any organization, not the caller's own.
    """
    if not isinstance(user, User) or not is_account_member_search_enabled(team, user):
        raise UserAccessControlError("account", "viewer")
    visible_accounts = UserAccessControl(user=user, team=team).filter_queryset_by_access_level(
        Account.objects.for_team(team.id)
    )
    try:
        account = visible_accounts.filter(id=account_id).values("external_id").first()
    except (ValidationError, ValueError):
        account = None
    if account is None:
        raise UserAccessControlError("account", "viewer", resource_id=account_id)
    try:
        return str(UUID(account["external_id"])) if account["external_id"] else None
    except ValueError:
        return None
