from datetime import timedelta
from functools import cached_property
from typing import Optional, Union, cast

from django.utils.timezone import now

from posthog.schema import HogQLQueryModifiers, MaterializationMode, ProductKey

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models import Team
from posthog.models.filters.utils import validate_group_type_index
from posthog.models.property import GroupTypeIndex
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.queries.actor_base_query import (
    SerializedActor,
    SerializedGroup,
    SerializedPerson,
    get_groups,
    get_serialized_people,
)


class RelatedActorsQuery:
    """
    This query calculates other groups and persons that are related to a person or a group.

    Two actors are considered related if they have had shared events in the past 90 days.
    """

    def __init__(
        self,
        team: Team,
        group_type_index: Optional[Union[GroupTypeIndex, str]],
        id: str,
    ):
        self.team = team
        self.group_type_index = validate_group_type_index("group_type_index", group_type_index)
        self.id = id
        # Treat a missing group key as the empty string (not NULL), matching the legacy raw query
        # which read the non-nullable materialized `$group_N` column directly. This keeps the
        # `(index, key)` tuples in the IN-subquery non-nullable.
        self._modifiers = HogQLQueryModifiers(materializationMode=MaterializationMode.LEGACY_NULL_AS_STRING)

    @property
    def is_aggregating_by_groups(self) -> bool:
        return self.group_type_index is not None

    def run(self) -> list[SerializedActor]:
        tag_queries(product=ProductKey.PRODUCT_ANALYTICS, feature=Feature.QUERY)
        results: list[SerializedActor] = []
        results.extend(self._query_related_people())

        from posthog.models.group_type_mapping import get_group_types_for_project

        group_type_indexes = [
            m["group_type_index"]
            for m in get_group_types_for_project(self.team.project_id)
            if m["group_type_index"] != self.group_type_index
        ]

        results.extend(self._query_related_groups(group_type_indexes=group_type_indexes))
        return results

    def _query_related_people(self) -> list[SerializedPerson]:
        if not self.is_aggregating_by_groups:
            return []
        tag_queries(name="related-people")
        person_ids = self._query_related_people_ids()
        with personhog_caller_tag("persons/related-actors"):
            return get_serialized_people(self.team, person_ids)

    def _group_key_field(self, group_index: int) -> ast.Expr:
        # Read the group key from the raw event JSON rather than the `$group_N` field: the latter is
        # zeroed for events older than the GroupTypeMapping.created_at, but the legacy raw query
        # matched all events regardless, so we go to the JSON to preserve that behavior.
        # JSONExtractString returns a non-nullable String (empty when missing), matching the
        # materialized column's type so tuple/IN comparisons stay non-nullable.
        return ast.Call(
            name="JSONExtractString",
            args=[ast.Field(chain=["events", "properties"]), ast.Constant(value=f"$group_{group_index}")],
        )

    def _query_related_people_ids(self) -> list:
        # Resolve distinct_ids seen on events for this group, then map them to persons via
        # `person_distinct_ids` — that table already applies the argMax(version) dedup and drops
        # deleted (is_deleted=1) mappings, matching the legacy person_distinct_id2 query.
        query = parse_select(
            """
            SELECT DISTINCT person_id
            FROM person_distinct_ids
            WHERE distinct_id IN (
                SELECT distinct_id
                FROM events
                WHERE timestamp > {after}
                  AND timestamp < {before}
                  AND {group_filter}
            )
            """,
            placeholders={
                "after": ast.Constant(value=self._after),
                "before": ast.Constant(value=self._before),
                "group_filter": ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=self._group_key_field(cast(int, self.group_type_index)),
                    right=ast.Constant(value=self.id),
                ),
            },
        )
        response = execute_hogql_query(query, team=self.team, modifiers=self._modifiers)
        return [row[0] for row in response.results]

    def _query_related_groups(self, group_type_indexes: list[int]) -> list:
        if not list(group_type_indexes):
            return []

        # Fan each event out into one (group_type_index, group_key) row per requested group type,
        # dropping empty keys, and collect the distinct pairs the actor co-occurred with. Existence
        # against the groups table is enforced later by get_groups (which only returns real groups),
        # so a key seen on events but missing from groups is dropped — matching the legacy query.
        array_join_list = ast.Array(
            exprs=[
                ast.Tuple(
                    exprs=[
                        ast.Constant(value=index),
                        self._group_key_field(index),
                    ]
                )
                for index in group_type_indexes
            ]
        )

        if self.is_aggregating_by_groups:
            actor_filter: ast.Expr = ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=self._group_key_field(cast(int, self.group_type_index)),
                right=ast.Constant(value=self.id),
            )
        else:
            actor_filter = ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["events", "person_id"]),
                right=ast.Constant(value=self.id),
            )

        query = parse_select(
            """
            SELECT DISTINCT tuples.1 AS group_type_index, tuples.2 AS group_key
            FROM events
            ARRAY JOIN arrayFilter(x -> x.2 != '', {array_join_list}) AS tuples
            WHERE timestamp > {after}
              AND timestamp < {before}
              AND {actor_filter}
            """,
            placeholders={
                "array_join_list": array_join_list,
                "after": ast.Constant(value=self._after),
                "before": ast.Constant(value=self._before),
                "actor_filter": actor_filter,
            },
        )
        response = execute_hogql_query(query, team=self.team, modifiers=self._modifiers)
        results = response.results
        if not results:
            return []

        serialized_results: list[SerializedGroup] = []
        for index in group_type_indexes:
            group_keys = sorted({result[1] for result in results if result[0] == index and result[1]})
            _, serialized_groups = get_groups(self.team.pk, index, group_keys)
            serialized_results.extend(serialized_groups)

        return serialized_results

    @cached_property
    def _after(self):
        return now() - timedelta(days=90)

    @cached_property
    def _before(self):
        return now()
