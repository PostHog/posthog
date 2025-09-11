from typing import Literal, Optional, cast

from django.db import connection, connections

import orjson as json

from posthog.schema import ActorsQuery, InsightActorsQuery, TrendsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.utils.recordings_helper import RecordingsHelper
from posthog.models import Group, Team


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

    # This is hand written instead of using the ORM because the ORM was blowing up the memory on exports and taking forever
    def get_actors(self, actor_ids, order_by: str = "") -> dict[str, dict]:
        # If actor queries start quietly dying again, this might need batching at some point
        # but currently works with 800,000 persondistinctid entries (May 24, 2024)
        persons_query = """SELECT posthog_person.id, posthog_person.uuid, posthog_person.properties, posthog_person.is_identified, posthog_person.created_at
            FROM posthog_person
            WHERE posthog_person.uuid = ANY(%(uuids)s)
            AND posthog_person.team_id = %(team_id)s"""
        if order_by:
            persons_query += f" ORDER BY {order_by}"

        conn = connections["persons_db_reader"] if "persons_db_reader" in connections else connection

        with conn.cursor() as cursor:
            cursor.execute(
                persons_query,
                {"uuids": list(actor_ids), "team_id": self.team.pk},
            )
            people = cursor.fetchall()
            cursor.execute(
                """SELECT posthog_persondistinctid.person_id, posthog_persondistinctid.distinct_id
            FROM posthog_persondistinctid
            WHERE posthog_persondistinctid.person_id = ANY(%(people_ids)s)
            AND posthog_persondistinctid.team_id = %(team_id)s""",
                {"people_ids": [x[0] for x in people], "team_id": self.team.pk},
            )
            distinct_ids = cursor.fetchall()

        person_id_to_raw_person_and_set: dict[int, tuple] = {person[0]: (person, []) for person in people}

        for pdid in distinct_ids:
            person_id_to_raw_person_and_set[pdid[0]][1].append(pdid[1])
        del distinct_ids

        person_uuid_to_person = {
            str(person[1]): {
                "id": person[1],
                "properties": json.loads(person[2]),
                "is_identified": person[3],
                "created_at": person[4],
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

        if self.query.search is not None and self.query.search != "":
            where_exprs.append(
                ast.Or(
                    exprs=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Field(chain=["properties", "email"]),
                            right=ast.Constant(value=f"%{self.query.search}%"),
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Field(chain=["properties", "name"]),
                            right=ast.Constant(value=f"%{self.query.search}%"),
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Call(name="toString", args=[ast.Field(chain=["id"])]),
                            right=ast.Constant(value=f"%{self.query.search}%"),
                        ),
                        parse_expr(
                            "id in (select person_id from person_distinct_ids where ilike(distinct_id, {search}))",
                            {"search": ast.Constant(value=f"%{self.query.search}%")},
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

        if self.query.search is not None and self.query.search != "":
            where_exprs.append(
                ast.Or(
                    exprs=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Field(chain=["properties", "name"]),
                            right=ast.Constant(value=f"%{self.query.search}%"),
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Call(name="toString", args=[ast.Field(chain=["key"])]),
                            right=ast.Constant(value=f"%{self.query.search}%"),
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
