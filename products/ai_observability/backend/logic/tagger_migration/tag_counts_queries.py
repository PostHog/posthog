from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries, tags_context
from posthog.models import Team

from products.ai_observability.backend.models.evaluation_configs import MAX_CATEGORICAL_OPTIONS

RECENT_DAYS = 30
# One more than an evaluation can hold, so a tagger that sent too many different tags shows as such.
MAX_SENT_TAG_NAMES = MAX_CATEGORICAL_OPTIONS + 1

_QUERY = """
SELECT properties.$ai_tagger_id AS tagger_id, count() AS tags
FROM events
WHERE event = '$ai_tag'
  AND timestamp >= now() - toIntervalDay({days})
  AND properties.$ai_tagger_id IN {tagger_ids}
GROUP BY tagger_id
LIMIT {limit}
"""

_SENT_TAGS_QUERY = """
SELECT properties.$ai_tagger_id AS tagger_id,
       groupUniqArrayArray({max_names})(JSONExtract(ifNull(properties.$ai_tags, '[]'), 'Array(String)')) AS names
FROM events
WHERE event = '$ai_tag'
  AND timestamp >= now() - toIntervalDay({days})
  AND properties.$ai_tagger_id IN {tagger_ids}
GROUP BY tagger_id
LIMIT {limit}
"""


def _run(team: Team, name: str, query: str, tagger_ids: list[str], **placeholders: ast.Expr) -> list:
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.MIGRATION, team_id=team.pk):
        tag_queries(name=name)
        response = execute_hogql_query(
            query=parse_select(
                query,
                placeholders={
                    "days": ast.Constant(value=RECENT_DAYS),
                    # Without an explicit limit HogQL caps the rows, and a missing tagger would read as silent.
                    "limit": ast.Constant(value=len(tagger_ids)),
                    "tagger_ids": ast.Tuple(exprs=[ast.Constant(value=tagger_id) for tagger_id in tagger_ids]),
                    **placeholders,
                },
            ),
            team=team,
            query_type=name,
            context=HogQLContext(team_id=team.pk, team=team, database=Database.create_for_posthog_tables(team)),
        )
    return response.results or []


def load_recent_tag_counts(team: Team, tagger_ids: list[str]) -> dict[str, int]:
    """Runs of each tagger in the last RECENT_DAYS days: one $ai_tag event per run, with or without tags. A tagger that
    did not run is missing from the result."""
    if not tagger_ids:
        return {}
    rows = _run(team, "tagger_migration_recent_tags", _QUERY, tagger_ids)
    return {str(tagger_id): int(tags) for tagger_id, tags in rows}


def load_sent_tag_names(team: Team, tagger_ids: list[str]) -> dict[str, tuple[str, ...]]:
    """The different tag names each tagger sent in the last RECENT_DAYS days, sorted, at most MAX_SENT_TAG_NAMES."""
    if not tagger_ids:
        return {}
    rows = _run(
        team,
        "tagger_migration_sent_tags",
        _SENT_TAGS_QUERY,
        tagger_ids,
        max_names=ast.Constant(value=MAX_SENT_TAG_NAMES),
    )
    return {str(tagger_id): tuple(sorted(names)) for tagger_id, names in rows if names}
