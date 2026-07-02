import uuid as uuid_mod
from datetime import UTC, datetime
from typing import Literal, Optional, cast

import orjson as json
import structlog

from posthog.schema import ActorsQuery, InsightActorsQuery, TrendsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.utils.recordings_helper import RecordingsHelper
from posthog.models import Team
from posthog.models.person.util import _batched_get_distinct_ids_for_persons, _batched_get_persons_by_uuids
from posthog.models.user import User
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.utils import is_anonymous_id

logger = structlog.get_logger(__name__)


class ActorStrategy:
    field: str
    origin: str
    origin_id: str

    def __init__(
        self,
        team: Team,
        query: ActorsQuery,
        paginator: HogQLHasMorePaginator,
        user: User | None = None,
    ):
        self.team = team
        self.paginator = paginator
        self.query = query
        self.user = user

    def get_actors(self, actor_ids) -> dict[str, dict]:
        raise NotImplementedError()

    def get_recordings(self, matching_events) -> dict[str, list[dict]]:
        return RecordingsHelper(self.team, user=self.user).get_recordings(matching_events)

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

    # Default 101 matches the canonical ClickHouse person query (groupArray(101)): consumers read
    # distinct_ids[0] or the display-name scorer, none needs the full set. get_serialized_people
    # overrides with its own distinct_id_limit for the persons-list/export API.
    def get_actors(
        self, actor_ids, sort_by_created_at_descending: bool = False, limit_per_person: int | None = 101
    ) -> dict[str, dict]:
        from posthog.personhog_client.client import personhog_call

        result = personhog_call(
            "get_actors",
            lambda: self._get_actors_via_personhog(actor_ids, sort_by_created_at_descending, limit_per_person),
        )

        # Surface identified (non-anonymous) distinct IDs first so consumers that read distinct_ids[0]
        # (person links, CSV exports) get the user-defined ID rather than an auto-generated anonymous one.
        # Mirrors PersonSerializer.to_representation, which sorts the same way for the persons API.
        for person in result.values():
            person["distinct_ids"] = sorted(person["distinct_ids"], key=is_anonymous_id)

        return result

    def _get_actors_via_personhog(
        self,
        actor_ids,
        sort_by_created_at_descending: bool,
        limit_per_person: int | None,
    ) -> dict[str, dict]:
        actor_ids_list = [str(uid) for uid in actor_ids]
        team_id = self.team.pk

        with personhog_caller_tag("persons/hogql-actors"):
            all_persons = _batched_get_persons_by_uuids(team_id, actor_ids_list, operation="get_actors")

            if sort_by_created_at_descending:
                all_persons.sort(key=lambda p: (-p.created_at, p.uuid))

            person_ids = [p.id for p in all_persons]
            distinct_ids_by_person = _batched_get_distinct_ids_for_persons(
                team_id, person_ids, limit_per_person=limit_per_person
            )

        return {
            p.uuid: {
                "id": uuid_mod.UUID(p.uuid),
                "properties": json.loads(p.properties) if p.properties else {},
                "is_identified": p.is_identified,
                "created_at": datetime.fromtimestamp(p.created_at / 1000, tz=UTC) if p.created_at else None,
                "last_seen_at": datetime.fromtimestamp(p.last_seen_at / 1000, tz=UTC) if p.last_seen_at else None,
                "distinct_ids": distinct_ids_by_person.get(p.id, []),
            }
            for p in all_persons
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
        from posthog.models.group.util import get_groups_by_identifiers

        groups = get_groups_by_identifiers(self.team.pk, self.group_type_index, [str(aid) for aid in actor_ids])
        return {
            str(g.group_key): {
                "id": g.group_key,
                "type": "group",
                "properties": g.group_properties,  # TODO: Legacy for frontend
                "group_key": g.group_key,
                "group_type_index": g.group_type_index,
                "created_at": g.created_at,
                "group_properties": g.group_properties,
            }
            for g in groups
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
            user=self.user,
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
