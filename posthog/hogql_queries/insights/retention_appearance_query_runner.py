from datetime import timedelta
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Union,
    cast,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext, get_max_limit_for_context, get_default_limit_for_context
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.retention_query_runner import RetentionQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models import Team
from posthog.queries.actor_base_query import get_groups, get_people, SerializedGroup, SerializedPerson
from posthog.schema import HogQLQueryModifiers, RetentionAppearanceQuery, PersonsQueryResponse


class HogQlHasMorePaginator:
    """
    Paginator that fetches one more result than requested to determine if there are more results.
    Takes care of setting the limit and offset on the query.
    """

    def __init__(self, limit: int, offset: int):
        self.limit = limit
        self.offset = offset

    def paginate(self, query: ast.SelectQuery) -> ast.SelectQuery:
        query.limit = ast.Constant(value=self.limit + 1)
        query.offset = ast.Constant(value=self.offset or 0)
        return query

    def has_more(self, results: List[Any]) -> bool:
        return len(results) > self.limit

    def trim_results(self, results: List[Any]) -> List[Any]:
        return results[:-1]


class RetentionAppearanceQueryRunner(QueryRunner):
    query: RetentionAppearanceQuery
    query_type = RetentionAppearanceQuery

    def __init__(
        self,
        query: RetentionAppearanceQuery | Dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)
        self.paginator = HogQlHasMorePaginator(limit=self.query_limit(), offset=self.query.offset or 0)

    def query_limit(self) -> int:
        # TODO: Reuse from somewhere else
        max_rows = get_max_limit_for_context(self.limit_context)
        default_rows = get_default_limit_for_context(self.limit_context)
        return min(max_rows, default_rows if self.query.limit is None else self.query.limit)

    def get_source_query_runner(self) -> RetentionQueryRunner:
        return cast(RetentionQueryRunner, get_query_runner(self.query.source, self.team, self.timings))

    def to_query(self) -> ast.SelectQuery:
        placeholders = {
            "actor_query": self.get_source_query_runner().actor_query(
                breakdown_values_filter=[self.query.selectedInterval]
            ),
        }
        with self.timings.measure("retention_query"):
            retention_query = parse_select(
                """
                    SELECT
                        actor_id,
                        groupArray(actor_activity.intervals_from_base) AS appearances

                    FROM {actor_query} AS actor_activity

                    GROUP BY actor_id

                    -- make sure we have stable ordering/pagination
                    -- NOTE: relies on ids being monotonic
                    ORDER BY
                        length(appearances) DESC,
                        actor_id
                """,
                placeholders,
                timings=self.timings,
            )
        return retention_query

    def to_persons_query(self) -> ast.SelectQuery:
        appearances_query = self.to_query()
        # Only select actor_id for the persons query
        appearances_query.select = [ast.Field(chain=["actor_id"])]
        appearances_query.order_by = []
        return appearances_query

    def get_actors_from_result(self, raw_result) -> Union[List[SerializedGroup], List[SerializedPerson]]:
        # TODO: Overhaul by leveraging common functionality in PersonsQueryRunner

        serialized_actors: Union[List[SerializedGroup], List[SerializedPerson]]

        actor_ids = [row[0] for row in raw_result]
        value_per_actor_id = None

        if self.query.source.aggregation_group_type_index is not None:
            _, serialized_actors = get_groups(
                self.team.pk,
                self.query.source.aggregation_group_type_index,
                actor_ids,
                value_per_actor_id,
            )
        else:
            _, serialized_actors = get_people(self.team, actor_ids, value_per_actor_id)

        return serialized_actors

    def calculate(self) -> PersonsQueryResponse:
        response = execute_hogql_query(
            query_type="RetentionQuery",
            query=self.paginator.paginate(self.to_query()),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        results = self.paginator.trim_results(response.results)
        has_more = self.paginator.has_more(response.results)

        actor_appearances = [
            {"actor_id": str(row[0]), "appearance_count": len(row[1]), "appearances": row[1]} for row in results
        ]

        serialized_actors = self.get_actors_from_result(
            [(actor_appearance["actor_id"],) for actor_appearance in actor_appearances]
        )

        actors_lookup = {str(actor["id"]): actor for actor in serialized_actors}

        actors = [
            [
                actors_lookup[actor["actor_id"]],
                [
                    1 if interval_number in actor["appearances"] else 0
                    for interval_number in range(
                        self.query.source.retentionFilter.total_intervals - (self.query.selectedInterval or 0)
                    )
                ],
            ]
            for actor in actor_appearances
            if actor["actor_id"] in actors_lookup
        ]
        return PersonsQueryResponse(
            results=actors,
            timings=response.timings,
            types=[t for _, t in response.types],
            columns=["person", "appearances"],
            hogql=response.hogql,
            hasMore=has_more,
        )
        #   "missing_persons": len(actor_appearances) - len(actors),

    def _is_stale(self, cached_result_package):
        return True

    def _refresh_frequency(self):
        return timedelta(minutes=1)
