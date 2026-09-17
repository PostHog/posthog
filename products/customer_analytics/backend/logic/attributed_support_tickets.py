from typing import cast
from uuid import UUID

import structlog

from posthog.hogql import ast
from posthog.hogql.errors import QueryError, ResolutionError, TableAccessDeniedError
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import posthog_feature_flag_enabled

from products.customer_analytics.backend.constants import CUSTOMER_ANALYTICS_CSP_FLAG

logger = structlog.get_logger(__name__)

# A saved query that resolves a customer org for every support ticket, including the
# backlog from before the support product recorded an org itself. It reads cross-region
# Postgres sources that only the PostHog org has, so in every other project the name does
# not resolve and the caller falls back to the ticket's own organization_id.
ATTRIBUTED_SUPPORT_TICKETS_VIEW = "support_tickets_attributed"

ATTRIBUTED_SUPPORT_TICKETS_MAX_TICKETS = 200

# The method the support product's own organization_id stands for. The view uses the same
# name for that case, so the fallback path and the view path share one vocabulary.
NATIVE_ATTRIBUTION_METHOD = "native"


@frozen
class AttributedTicketRef:
    ticket_id: str
    attribution_method: str


def is_attributed_support_tickets_enabled(team: Team, user: User) -> bool:
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


def _parse_rows(rows: list[list[object]]) -> tuple[AttributedTicketRef, ...]:
    refs: list[AttributedTicketRef] = []
    for row in rows:
        if len(row) < 2 or row[0] is None:
            continue
        try:
            ticket_id = str(UUID(str(row[0])))
        except ValueError:
            # The view derives ids from warehouse data, so a row can carry something that is
            # not a ticket id. Skipping it keeps one bad row from failing the whole tab.
            continue
        refs.append(
            AttributedTicketRef(
                ticket_id=ticket_id,
                attribution_method=str(row[1]) if row[1] is not None else NATIVE_ATTRIBUTION_METHOD,
            )
        )
    return tuple(refs)


def list_attributed_ticket_refs(
    *,
    team: Team,
    user: User,
    external_id: str,
    limit: int = ATTRIBUTED_SUPPORT_TICKETS_MAX_TICKETS,
) -> tuple[AttributedTicketRef, ...] | None:
    """Ticket ids attributed to ``external_id``, newest activity first, with the method that
    attributed each one.

    Returns ``None`` when the view is unavailable, which means the caller must fall back to
    the ticket's own organization_id. An empty tuple is different: the view answered and
    attributed no ticket to this account.
    """
    if not external_id or not is_attributed_support_tickets_enabled(team, user):
        return None

    capped_limit = max(1, min(limit, ATTRIBUTED_SUPPORT_TICKETS_MAX_TICKETS))
    try:
        with tags_context(product=Product.CUSTOMER_ANALYTICS, feature=Feature.QUERY):
            response = execute_hogql_query(
                query=f"""
                    SELECT ticket_id, attribution_method
                    FROM {ATTRIBUTED_SUPPORT_TICKETS_VIEW}
                    WHERE org_id = {{org_id}}
                    ORDER BY coalesce(last_message_at, created_at) DESC
                    LIMIT {capped_limit}
                """,
                placeholders={"org_id": ast.Constant(value=external_id)},
                team=team,
                user=user,
                query_type="customer_analytics_attributed_support_tickets",
            )
    except (ResolutionError, TableAccessDeniedError) as error:
        logger.info(
            "attributed_support_tickets_unavailable",
            team_id=team.id,
            error_type=type(error).__name__,
        )
        return None
    except QueryError as error:
        logger.warning(
            "attributed_support_tickets_failed",
            team_id=team.id,
            error_type=type(error).__name__,
        )
        return None
    except Exception as error:
        logger.warning(
            "attributed_support_tickets_failed",
            team_id=team.id,
            error_type=type(error).__name__,
        )
        return None

    return _parse_rows(cast(list[list[object]], response.results or []))
