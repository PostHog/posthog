from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries, tags_context
from posthog.models import Team

RECENT_DAYS = 30

_QUERY = """
SELECT properties.$ai_tagger_id AS tagger_id, count() AS tags
FROM events
WHERE event = '$ai_tag'
  AND timestamp >= now() - toIntervalDay({days})
  AND properties.$ai_tagger_id IN {tagger_ids}
GROUP BY tagger_id
"""


def load_recent_tag_counts(team: Team, tagger_ids: list[str]) -> dict[str, int]:
    """Tags each tagger sent in the last RECENT_DAYS days. A tagger that sent none is missing from the result."""
    if not tagger_ids:
        return {}
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.MIGRATION, team_id=team.pk):
        tag_queries(name="tagger_migration_recent_tags")
        response = execute_hogql_query(
            query=parse_select(
                _QUERY,
                placeholders={
                    "days": ast.Constant(value=RECENT_DAYS),
                    "tagger_ids": ast.Tuple(exprs=[ast.Constant(value=tagger_id) for tagger_id in tagger_ids]),
                },
            ),
            team=team,
            query_type="tagger_migration_recent_tags",
            context=HogQLContext(team_id=team.pk, team=team, database=Database.create_for_posthog_tables(team)),
        )
    return {str(tagger_id): int(tags) for tagger_id, tags in response.results or []}
