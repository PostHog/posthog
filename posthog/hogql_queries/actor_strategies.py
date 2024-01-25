from collections import defaultdict
from typing import Dict, List, cast, Literal, Optional

from django.db.models import Prefetch

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.models import Team, Person, Group
from posthog.schema import ActorsQuery
from posthog.session_recordings.models.session_recording import SessionRecording


class ActorStrategy:
    field: str
    origin: str
    origin_id: str

    def __init__(self, team: Team, query: ActorsQuery, paginator: HogQLHasMorePaginator):
        self.team = team
        self.paginator = paginator
        self.query = query

    def get_actors(self, actor_ids) -> Dict[str, Dict]:
        raise NotImplementedError()

    def get_recordings(self, matching_events) -> dict[str, list[dict]]:
        return {}

    def input_columns(self) -> List[str]:
        raise NotImplementedError()

    def filter_conditions(self) -> List[ast.Expr]:
        return []

    def order_by(self) -> Optional[List[ast.OrderExpr]]:
        return None


class PersonStrategy(ActorStrategy):
    field = "person"
    origin = "persons"
    origin_id = "id"

    def get_actors(self, actor_ids) -> Dict[str, Dict]:
        return {
            str(p.uuid): {
                "id": p.uuid,
                **{field: getattr(p, field) for field in ("distinct_ids", "properties", "created_at", "is_identified")},
            }
            for p in Person.objects.filter(
                team_id=self.team.pk, persondistinctid__team_id=self.team.pk, uuid__in=actor_ids
            )
            .prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))
            .iterator(chunk_size=self.paginator.limit)
        }

    def session_ids_all(self, session_ids) -> set[str]:
        query = """
          SELECT DISTINCT session_id
          FROM session_replay_events
          WHERE session_id in {session_ids}
          """

        # TODO: Date filters

        response = execute_hogql_query(
            query,
            placeholders={"session_ids": ast.Array(exprs=[ast.Constant(value=s) for s in session_ids])},
            team=self.team,
        )
        return {str(result[0]) for result in response.results}

    def session_ids_with_deleted_recordings(self, session_ids) -> set[str]:
        return set(
            SessionRecording.objects.filter(team_id=self.team.pk, session_id__in=session_ids, deleted=True).values_list(
                "session_id", flat=True
            )
        )

    def get_recordings(self, matching_events) -> dict[str, list[dict]]:
        mapped_events = defaultdict(list)
        for event in matching_events:
            mapped_events[event[2]].append(event)

        raw_session_ids = mapped_events.keys()
        valid_session_ids = self.session_ids_all(raw_session_ids) - self.session_ids_with_deleted_recordings(
            raw_session_ids
        )

        return {
            str(session_id): [
                {
                    "timestamp": event[0],
                    "uuid": event[1],
                    "window_id": event[3],
                }
                for event in events
            ]
            for session_id, events in mapped_events.items()
            if session_id in valid_session_ids and len(events) > 0
        }

    def input_columns(self) -> List[str]:
        return ["person", "id", "created_at", "person.$delete"]

    def filter_conditions(self) -> List[ast.Expr]:
        where_exprs: List[ast.Expr] = []

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
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Field(chain=["pdi", "distinct_id"]),
                            right=ast.Constant(value=f"%{self.query.search}%"),
                        ),
                    ]
                )
            )
        return where_exprs

    def order_by(self) -> Optional[List[ast.OrderExpr]]:
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

    def get_actors(self, actor_ids) -> Dict[str, Dict]:
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

    def input_columns(self) -> List[str]:
        return ["group"]

    def filter_conditions(self) -> List[ast.Expr]:
        where_exprs: List[ast.Expr] = []

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

    def order_by(self) -> Optional[List[ast.OrderExpr]]:
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
