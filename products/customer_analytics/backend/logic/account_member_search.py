from typing import cast

import structlog

from posthog.hogql import ast
from posthog.hogql.errors import QueryError, ResolutionError, TableAccessDeniedError
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.constants import INTERNAL_BOT_EMAIL_SUFFIX
from posthog.models import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import posthog_feature_flag_enabled

from products.customer_analytics.backend.constants import CUSTOMER_ANALYTICS_CSP_FLAG

logger = structlog.get_logger(__name__)

ACCOUNT_MEMBER_SEARCH_MAX_ORGANIZATIONS = 100
EU_ORGANIZATION_MEMBERS_VIEW = "eu_org_members"


def _is_account_member_search_enabled(team: Team, user: User) -> bool:
    return user.is_staff and posthog_feature_flag_enabled(
        CUSTOMER_ANALYTICS_CSP_FLAG,
        str(user.distinct_id),
        organization_id=team.organization_id,
        team_id=team.id,
    )


def get_account_member_search_staff_user(team: Team) -> User | None:
    active_memberships = OrganizationMembership.objects.filter(
        organization_id=team.organization_id,
        user__is_active=True,
    )
    if active_memberships.filter(user__is_staff=False).exists():
        return None

    staff_user = (
        User.objects.filter(
            organization_membership__organization_id=team.organization_id,
            is_active=True,
            is_staff=True,
        )
        .order_by("id")
        .first()
    )
    if staff_user is None or not _is_account_member_search_enabled(team, staff_user):
        return None
    return staff_user


def _list_us_organization_ids(email: str) -> tuple[str, ...]:
    if email.endswith(INTERNAL_BOT_EMAIL_SUFFIX):
        return ()
    organization_ids = (
        OrganizationMembership.objects.filter(user__email=email, user__is_active=True)
        .order_by("organization_id")
        .values_list("organization_id", flat=True)[:ACCOUNT_MEMBER_SEARCH_MAX_ORGANIZATIONS]
    )
    return tuple(str(organization_id) for organization_id in organization_ids)


def _list_eu_organization_ids(team: Team, user: User, email: str) -> tuple[str, ...]:
    try:
        with tags_context(product=Product.CUSTOMER_ANALYTICS, feature=Feature.QUERY):
            response = execute_hogql_query(
                query=f"""
                    SELECT DISTINCT organization_id
                    FROM {EU_ORGANIZATION_MEMBERS_VIEW}
                    WHERE email = {{email}}
                    ORDER BY organization_id
                    LIMIT {ACCOUNT_MEMBER_SEARCH_MAX_ORGANIZATIONS}
                """,
                placeholders={"email": ast.Constant(value=email)},
                team=team,
                user=user,
                query_type="customer_analytics_account_member_email_lookup",
            )
    except (ResolutionError, TableAccessDeniedError) as error:
        logger.info(
            "account_member_email_lookup_unavailable",
            team_id=team.id,
            error_type=type(error).__name__,
        )
        return ()
    except QueryError as error:
        logger.warning(
            "account_member_email_lookup_failed",
            team_id=team.id,
            error_type=type(error).__name__,
        )
        return ()
    except Exception as error:
        logger.warning(
            "account_member_email_lookup_failed",
            team_id=team.id,
            error_type=type(error).__name__,
        )
        return ()

    rows = cast(list[list[object]], response.results or [])
    return tuple(str(row[0]) for row in rows if row and row[0] is not None)


def list_account_external_ids_by_member_email(*, team: Team, user: User, email: str) -> tuple[str, ...]:
    if not _is_account_member_search_enabled(team, user):
        return ()

    organization_ids = _list_us_organization_ids(email)
    if organization_ids:
        return organization_ids
    return _list_eu_organization_ids(team, user, email)
