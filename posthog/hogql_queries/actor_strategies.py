from typing import Any, Literal, Optional, cast

from posthog.schema import ActorsQuery, InsightActorsQuery, TrendsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.utils.recordings_helper import RecordingsHelper
from posthog.models import Group, Team


def _parse_properties(properties: Any) -> dict:
    """Parse properties from ClickHouse which may be a string or dict."""
    if isinstance(properties, dict):
        return properties
    if isinstance(properties, str):
        import json

        try:
            return json.loads(properties)
        except json.JSONDecodeError:
            return {}
    return {}


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

    def get_actors(self, actor_ids, order_by: str = "") -> dict[str, dict]:
        actor_ids_list = list(actor_ids)
        if not actor_ids_list:
            return {}

        batch_size = 10000
        persons_result: list[tuple] = []
        for i in range(0, len(actor_ids_list), batch_size):
            batch = actor_ids_list[i : i + batch_size]
            batch_result = sync_execute(
                """
                SELECT id, argMax(properties, version), argMax(is_identified, version), argMax(created_at, version)
                FROM person
                WHERE team_id = %(team_id)s AND id IN %(actor_ids)s
                GROUP BY id
                HAVING argMax(is_deleted, version) = 0
                """,
                {"team_id": self.team.pk, "actor_ids": batch},
            )
            persons_result.extend(batch_result)

        if not persons_result:
            return {}

        person_ids = [str(row[0]) for row in persons_result]

        distinct_ids_result: list[tuple] = []
        for i in range(0, len(person_ids), batch_size):
            batch = person_ids[i : i + batch_size]
            batch_result = sync_execute(
                """
                SELECT person_id, groupArray(distinct_id)
                FROM person_distinct_id2
                WHERE team_id = %(team_id)s AND person_id IN %(person_ids)s
                GROUP BY person_id
                """,
                {"team_id": self.team.pk, "person_ids": batch},
            )
            distinct_ids_result.extend(batch_result)

        person_id_to_distinct_ids: dict[str, list[str]] = {str(row[0]): row[1] for row in distinct_ids_result}

        return {
            str(row[0]): {
                "id": row[0],
                "properties": _parse_properties(row[1]),
                "is_identified": row[2],
                "created_at": row[3],
                "distinct_ids": person_id_to_distinct_ids.get(str(row[0]), []),
            }
            for row in persons_result
        }

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
                            left=ast.Call(name="toString", args=[ast.Field(chain=["properties", "email"])]),
                            right=ast.Constant(value=f"%{self.query.search}%"),
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Call(name="toString", args=[ast.Field(chain=["properties", "name"])]),
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
