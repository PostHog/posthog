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
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.retention_query_runner import RetentionQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models import Team
from posthog.queries.actor_base_query import get_groups, get_people, SerializedGroup, SerializedPerson
from posthog.queries.retention.actors_query import AppearanceRow
from posthog.schema import HogQLQueryModifiers, RetentionAppearanceQuery


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
            retention_query.limit = ast.Constant(value=100)  # TODO: Limit
            retention_query.offset = ast.Constant(value=self.query.offset)
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

    def calculate(self) -> Any:  # TODO: new type?
        query = self.to_query()
        _hogql = to_printed_hogql(query, self.team.pk)

        response = execute_hogql_query(
            query_type="RetentionQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        results = response.results

        actor_appearances = [
            AppearanceRow(actor_id=str(row[0]), appearance_count=len(row[1]), appearances=row[1]) for row in results
        ]

        serialized_actors = self.get_actors_from_result(
            [(actor_appearance.actor_id,) for actor_appearance in actor_appearances]
        )

        actors_lookup = {str(actor["id"]): actor for actor in serialized_actors}

        actors = [
            {
                "person": actors_lookup[actor.actor_id],
                "appearances": [
                    1 if interval_number in actor.appearances else 0
                    for interval_number in range(
                        self.query.source.retentionFilter.total_intervals - (self.query.selectedInterval or 0)
                    )
                ],
            }
            for actor in actor_appearances
            if actor.actor_id in actors_lookup
        ]
        raw_count = len(actor_appearances)

        return {
            "result": actors,
            "next": "",
            "missing_persons": raw_count - len(actors),
        }

    def _is_stale(self, cached_result_package):
        return True

    def _refresh_frequency(self):
        return timedelta(minutes=1)
