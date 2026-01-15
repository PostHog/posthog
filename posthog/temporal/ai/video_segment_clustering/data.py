from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team


def count_distinct_persons(team: Team, distinct_ids: list[str]) -> int:
    """Count unique persons from a list of distinct_ids, using ClickHouse as the source of truth.

    (This util should probably be more general than video_segment_clustering, but really unsure what the right place is.)
    """
    if not distinct_ids:
        return 0
    result = execute_hogql_query(
        query_type="DistinctPersonCount",
        query=parse_select(
            """
            SELECT COUNT(DISTINCT person_id)
            FROM person_distinct_ids
            WHERE distinct_id IN {distinct_ids}"""
        ),
        placeholders={"distinct_ids": ast.Constant(value=distinct_ids)},
        team=team,
    )
    return result.results[0][0] if result.results and len(result.results) > 0 else 0
