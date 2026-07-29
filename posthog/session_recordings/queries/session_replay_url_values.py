from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import relative_date_parse

# The "visited page" filter matches against the URLs replay itself recorded, so its
# suggestions have to come from the same place rather than from $pageview events.
VISITED_PAGE_VALUES_LIMIT = 25
VISITED_PAGE_VALUES_DATE_FROM = "-30d"


def get_visited_page_values(
    *,
    team: Team,
    user: User | None = None,
    search_value: str | None = None,
    limit: int = VISITED_PAGE_VALUES_LIMIT,
) -> list[str]:
    """Distinct URLs seen in recordings of the last 30 days, for the visited page filter's value picker."""
    search = (search_value or "").strip()
    search_clause = "AND url ILIKE {search}" if search else ""
    # Shortest match first when searching; unordered otherwise so ClickHouse can stop
    # reading as soon as it has enough distinct URLs.
    order_by_clause = "ORDER BY length(url) ASC" if search else ""

    date_from = relative_date_parse(VISITED_PAGE_VALUES_DATE_FROM, team.timezone_info).strftime("%Y-%m-%d %H:%M:%S")
    date_to = timezone.now().astimezone(team.timezone_info).strftime("%Y-%m-%d %H:%M:%S")
    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "date_to": ast.Constant(value=date_to),
        "limit": ast.Constant(value=limit),
    }
    if search:
        placeholders["search"] = ast.Constant(value=f"%{_escape_like_pattern(search)}%")

    query = parse_select(
        f"""
        SELECT DISTINCT url
        FROM (
            SELECT arrayJoin(all_urls) AS url
            FROM raw_session_replay_events
            WHERE min_first_timestamp >= {{date_from}} AND min_first_timestamp <= {{date_to}}
        )
        WHERE url != '' {search_clause}
        {order_by_clause}
        LIMIT {{limit}}
        """,
        placeholders=placeholders,
    )

    tag_queries(product=Product.REPLAY, feature=Feature.QUERY, team_id=team.pk)
    response = execute_hogql_query(query, team=team, user=user, query_type="SessionReplayUrlValuesQuery")
    return [row[0] for row in response.results or []]


def _escape_like_pattern(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
