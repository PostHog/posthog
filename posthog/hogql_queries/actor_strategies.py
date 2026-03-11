from typing import Literal, Optional, cast

from django.db import connections

import orjson as json

from posthog.schema import ActorsQuery, InsightActorsQuery, TrendsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.utils.recordings_helper import RecordingsHelper
from posthog.models import Group, Team
from posthog.models.person import Person, PersonDistinctId
from posthog.person_db_router import PERSONS_DB_FOR_READ

# Use centralized database routing constant
READ_DB_FOR_PERSONS = PERSONS_DB_FOR_READ


class ActorStrategy:
    field: str
    origin: str
    origin_id: str

    def __init__(self, team: Team, query: ActorsQuery, paginator: HogQLHasMorePaginator):
        self.team = team
        self.paginator = paginator
        self.query = query

    def get_actors(self, actor_ids) -> dict[str, dict]:
        raise NotImplementedError()

    def get_recordings(self, matching_events) -> dict[str, list[dict]]:
        return RecordingsHelper(self.team).get_recordings(matching_events)

    def input_columns(self) -> list[str]:
        raise NotImplementedError()

    def filter_conditions(self) -> list[ast.Expr]:
        return []

    def order_by(self) -> Optional[list[ast.OrderExpr]]:
        return None


class PersonStrategy(ActorStrategy):
    field = "person"
    origin = "persons"
    origin_id = "id"

    # batching is needed to prevent timeouts when reading from Postgres
    BATCH_SIZE = 1000

    # This is hand written instead of using the ORM because the ORM was blowing up the memory on exports and taking forever
    def get_actors(self, actor_ids, sort_by_created_at_descending: bool = False) -> dict[str, dict]:
        person_table = Person._meta.db_table
        pdi_table = PersonDistinctId._meta.db_table
        conn = connections[READ_DB_FOR_PERSONS]

        actor_ids_list = list(actor_ids)
        all_people: list = []
        all_distinct_ids: list = []

        with conn.cursor() as cursor:
            for i in range(0, len(actor_ids_list), self.BATCH_SIZE):
                batch = actor_ids_list[i : i + self.BATCH_SIZE]
                persons_query = f"""SELECT {person_table}.id, {person_table}.uuid, {person_table}.properties, {person_table}.is_identified, {person_table}.created_at, {person_table}.last_seen_at
                    FROM {person_table}
                    WHERE {person_table}.uuid = ANY(%(uuids)s)
                    AND {person_table}.team_id = %(team_id)s"""
                cursor.execute(persons_query, {"uuids": batch, "team_id": self.team.pk})
                all_people.extend(cursor.fetchall())

            if sort_by_created_at_descending:
                from datetime import datetime

                min_dt = datetime.min
                all_people.sort(key=lambda p: (-(p[4] or min_dt).timestamp(), str(p[1])))

            person_ids = [x[0] for x in all_people]
            for i in range(0, len(person_ids), self.BATCH_SIZE):
                batch = person_ids[i : i + self.BATCH_SIZE]
                cursor.execute(
                    f"""SELECT {pdi_table}.person_id, {pdi_table}.distinct_id
                    FROM {pdi_table}
                    WHERE {pdi_table}.person_id = ANY(%(people_ids)s)
                    AND {pdi_table}.team_id = %(team_id)s""",
                    {"people_ids": batch, "team_id": self.team.pk},
                )
                all_distinct_ids.extend(cursor.fetchall())

        person_id_to_raw_person_and_set: dict[int, tuple] = {person[0]: (person, []) for person in all_people}

        for pdid in all_distinct_ids:
            person_id_to_raw_person_and_set[pdid[0]][1].append(pdid[1])
        del all_distinct_ids

        person_uuid_to_person = {
            str(person[1]): {
                "id": person[1],
                "properties": json.loads(person[2]),
                "is_identified": person[3],
                "created_at": person[4],
                "last_seen_at": person[5],
                "distinct_ids": distinct_ids,
            }
            for person, distinct_ids in person_id_to_raw_person_and_set.values()
        }

        return person_uuid_to_person

    def input_columns(self) -> list[str]:
        if isinstance(self.query.source, InsightActorsQuery) and isinstance(self.query.source.source, TrendsQuery):
            return ["person", "id", "person.$delete", "event_distinct_ids"]
        return ["person", "id", "person.$delete"]

    def filter_conditions(self) -> list[ast.Expr]:
        where_exprs: list[ast.Expr] = []

        if self.query.properties:
            where_exprs.append(property_to_expr(self.query.properties, self.team, scope="person"))

        if self.query.fixedProperties:
            where_exprs.append(property_to_expr(self.query.fixedProperties, self.team, scope="person"))

        search = self.query.search.strip() if self.query.search else None
        if search:
            where_exprs.append(
                ast.Or(
                    exprs=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Call(name="toString", args=[ast.Field(chain=["properties", "email"])]),
                            right=ast.Constant(value=f"%{search}%"),
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Call(name="toString", args=[ast.Field(chain=["properties", "name"])]),
                            right=ast.Constant(value=f"%{search}%"),
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Call(name="toString", args=[ast.Field(chain=["id"])]),
                            right=ast.Constant(value=f"%{search}%"),
                        ),
                        parse_expr(
                            "id in (select person_id from person_distinct_ids where ilike(distinct_id, {search}))",
                            {"search": ast.Constant(value=f"%{search}%")},
                        ),
                    ]
                )
            )
        return where_exprs

    def order_by(self) -> Optional[list[ast.OrderExpr]]:
        if self.query.orderBy not in [["person"], ["person DESC"], ["person ASC"]]:
            return None

        order_property = (
            "email" if self.team.person_display_name_properties is None else self.team.person_display_name_properties[0]
        )
        return [
            ast.OrderExpr(
                expr=ast.Field(chain=["properties", order_property]),
                order=cast(
                    Literal["ASC", "DESC"],
                    "DESC" if self.query.orderBy[0] == "person DESC" else "ASC",
                ),
            )
        ]


class GroupStrategy(ActorStrategy):
    field = "group"
    origin = "groups"
    origin_id = "key"

    def __init__(self, group_type_index: int, **kwargs):
        self.group_type_index = group_type_index
        super().__init__(**kwargs)

    def get_actors(self, actor_ids) -> dict[str, dict]:
        return {
            str(p["group_key"]): {
                "id": p["group_key"],
                "type": "group",
                "properties": p["group_properties"],  # TODO: Legacy for frontend
                **p,
            }
            for p in Group.objects.filter(
                team_id=self.team.pk, group_type_index=self.group_type_index, group_key__in=actor_ids
            )
            .values("group_key", "group_type_index", "created_at", "group_properties")
            .iterator(chunk_size=self.paginator.limit)
        }

    def input_columns(self) -> list[str]:
        return ["group"]

    def filter_conditions(self) -> list[ast.Expr]:
        where_exprs: list[ast.Expr] = []

        search = self.query.search.strip() if self.query.search else None
        if search:
            where_exprs.append(
                ast.Or(
                    exprs=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Field(chain=["properties", "name"]),
                            right=ast.Constant(value=f"%{search}%"),
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Call(name="toString", args=[ast.Field(chain=["key"])]),
                            right=ast.Constant(value=f"%{search}%"),
                        ),
                    ]
                )
            )

        return where_exprs

    def order_by(self) -> Optional[list[ast.OrderExpr]]:
        if self.query.orderBy not in [["group"], ["group DESC"], ["group ASC"]]:
            return None

        order_property = "name"
        return [
            ast.OrderExpr(
                expr=ast.Field(chain=["properties", order_property]),
                order=cast(
                    Literal["ASC", "DESC"],
                    "DESC" if self.query.orderBy[0] == "group DESC" else "ASC",
                ),
            )
        ]


class SessionStrategy(ActorStrategy):
    """Strategy for session-based aggregation (e.g. funnels aggregated by $session_id).

    The actor is a session. Person data is fetched separately using the person_id
    column from the funnel query and nested under a "person" key.
    """

    field = "session"
    origin = "sessions"
    origin_id = "session_id"

    def get_actors(self, actor_ids) -> dict[str, dict]:
        session_ids = list(actor_ids)
        if not session_ids:
            return {}

        query = parse_select(
            """
            SELECT
                session_id,
                `$start_timestamp`,
                `$end_timestamp`,
                `$session_duration`,
                `$channel_type`,
                `$entry_pathname`,
                `$entry_referring_domain`,
                `$entry_utm_source`,
                `$entry_utm_medium`,
                `$entry_utm_campaign`,
                `$entry_utm_term`,
                `$entry_utm_content`,
                `$num_uniq_urls`,
                `$autocapture_count`,
                `$exit_pathname`,
                `$last_external_click_url`,
                `$pageview_count`
            FROM sessions
            WHERE session_id IN {session_ids}
            """,
            {"session_ids": ast.Constant(value=session_ids)},
        )

        response = execute_hogql_query(
            query_type="SessionActorsQuery",
            query=query,
            team=self.team,
        )

        columns = response.columns or []
        return {str(row[0]): {columns[i]: row[i] for i in range(len(columns))} for row in response.results}

    def input_columns(self) -> list[str]:
        return ["session"]

    def filter_conditions(self) -> list[ast.Expr]:
        where_exprs: list[ast.Expr] = []

        search = self.query.search.strip() if self.query.search else None
        if search:
            where_exprs.append(
                parse_expr(
                    "person_id in (select id from persons where ilike(properties.email, {search}) or ilike(properties.name, {search}))",
                    {"search": ast.Constant(value=f"%{search}%")},
                )
            )
        return where_exprs
