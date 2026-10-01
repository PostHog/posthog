from datetime import timedelta
from functools import cached_property
from typing import Optional, Union, cast

from django.utils.timezone import now

import grpc

from posthog.schema import HogQLQueryModifiers, MaterializationMode, ProductKey

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.hogql_queries.serialized_actors import (
    SerializedActor,
    SerializedGroup,
    SerializedPerson,
    get_groups,
    get_serialized_people,
)
from posthog.models import Team
from posthog.models.filters.utils import validate_group_type_index
from posthog.models.person.person import MAX_LIMIT_DISTINCT_IDS
from posthog.models.person.util import get_distinct_ids_for_person, get_person_ids_and_uuids_by_uuids
from posthog.models.property import GroupTypeIndex
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.personhog_client.interceptor import is_transient_rpc_error


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

    @cached_property
    def _person_id(self) -> int | None:
        with personhog_caller_tag("persons/related-actors"):
            persons = get_person_ids_and_uuids_by_uuids(self.team.pk, [self.id])
        if not persons:
            return None
        person_id, _ = persons[0]
        return person_id

    def _person_distinct_ids(self) -> list[str]:
        try:
            if self._person_id is None:
                return []

            # ClickHouse merge updates can arrive before the personhog read replica catches up.
            distinct_ids = get_distinct_ids_for_person(
                self.team.pk,
                self._person_id,
                limit=MAX_LIMIT_DISTINCT_IDS,
                consistency="strong",
                caller_tag="persons/related-actors",
            )
        except grpc.RpcError as exc:
            if not is_transient_rpc_error(exc):
                raise
            # The identity lookup only selects the fast path; client retries already recorded this failure.
            return []

        # Personhog caps limited lookups at MAX_LIMIT_DISTINCT_IDS, so a full batch may be
        # incomplete. Keep the person_id predicate in that case, and for event-only persons.
        return distinct_ids if len(distinct_ids) < MAX_LIMIT_DISTINCT_IDS else []

    def _person_filter(self, distinct_ids: list[str]) -> ast.Expr:
        if distinct_ids:
            # Current distinct IDs include merged history and let ClickHouse filter events
            # before reading group keys, without joining the project's person overrides.
            return ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["events", "distinct_id"]),
                right=ast.Tuple(exprs=[ast.Constant(value=distinct_id) for distinct_id in distinct_ids]),
            )

        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["events", "person_id"]),
            right=ast.Constant(value=self.id),
        )

    def _query_related_groups(self, group_type_indexes: list[int], *, force_person_id: bool = False) -> list:
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

        distinct_ids: list[str] = []
        if self.is_aggregating_by_groups:
            actor_filter: ast.Expr = ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=self._group_key_field(cast(int, self.group_type_index)),
                right=ast.Constant(value=self.id),
            )
        else:
            distinct_ids = [] if force_person_id else self._person_distinct_ids()
            actor_filter = self._person_filter(distinct_ids)

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
        # A merge can commit after the initial identity read and before the event query finishes.
        if distinct_ids and set(distinct_ids) != set(self._person_distinct_ids()):
            return self._query_related_groups(group_type_indexes, force_person_id=True)
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
