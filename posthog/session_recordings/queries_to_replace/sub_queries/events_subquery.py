from datetime import datetime, timedelta
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.legacy_compatibility.filter_to_query import legacy_entity_to_node, MathAvailability
from posthog.models import Team, Entity
from posthog.schema import (
    RecordingsQuery,
    HogQLQueryModifiers,
)
from posthog.session_recordings.queries_to_replace.sub_queries.base_query import SessionRecordingsListingBaseQuery
from posthog.session_recordings.queries_to_replace.utils import (
    INVERSE_OPERATOR_FOR,
    NEGATIVE_OPERATORS,
    SessionRecordingQueryResult,
    _entity_to_expr,
    is_event_property,
    is_group_property,
    is_person_property,
)
from posthog.types import AnyPropertyFilter


class ReplayFiltersEventsSubQuery(SessionRecordingsListingBaseQuery):
    def __init__(
        self,
        team: Team,
        query: RecordingsQuery,
        hogql_query_modifiers: Optional[HogQLQueryModifiers] = None,
    ):
        super().__init__(team, query)
        self._hogql_query_modifiers = hogql_query_modifiers

    @property
    def _event_predicates(self) -> list[ast.Expr]:
        event_exprs: list[ast.Expr] = []

        for entity in self.entities:
            # this is always _positive_ operations
            entity_exprs = [_entity_to_expr(entity=entity)]

            if entity.properties:
                entity_exprs.append(property_to_expr(entity.properties, team=self._team, scope="replay_entity"))

            event_exprs.append(ast.And(exprs=entity_exprs))

        return event_exprs

    @property
    def _negative_event_predicates(self) -> list[ast.Expr]:
        event_exprs: list[ast.Expr] = []

        for entity in self.entities:
            # the entity itself is always a positive expression,
            # so we don't need to check it here where we're looking only
            # for negative items to check across the session
            entity_exprs = []

            for prop in entity.properties or []:
                # TODO how can we make this work for HogQL property filters
                if "operator" in prop and prop.operator in NEGATIVE_OPERATORS:
                    entity_exprs.append(property_to_expr(entity.properties, team=self._team, scope="replay_entity"))

            if entity_exprs:
                event_exprs.append(ast.And(exprs=entity_exprs))

        return event_exprs

    def _select_from_events(self, select_expr: ast.Expr, where_expr: ast.Expr | list[ast.Expr]) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=[select_expr],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"]),
            ),
            where=self._where_predicates(where_expr),
            having=self._having_predicates(),
            group_by=[ast.Field(chain=["$session_id"])],
            order_by=[ast.OrderExpr(expr=ast.Call(name="min", args=[ast.Field(chain=["timestamp"])]), order="DESC")],
        )

    def _get_queries_for_matching(self, select_expr: ast.Expr) -> list[ast.SelectQuery]:
        """
        takes each filter in the query that can be queried from the events table
        and makes a separate query for each
        this might be slower than the previous approach of having one huge event query
        but that approach is horribly complex and we keep getting bug reports
        that are avoidable with a simpler approach
        """
        gathered_exprs: list[ast.Expr] = []
        event_where_exprs = self._event_predicates
        if event_where_exprs:
            gathered_exprs += event_where_exprs

        for p in self.event_properties:
            gathered_exprs.append(
                property_to_expr(
                    p,
                    team=self._team,
                    scope="replay",
                )
            )

        for p in self.group_properties:
            gathered_exprs.append(property_to_expr(p, team=self._team))

        if self._team.person_on_events_mode and self.person_properties:
            for p in self.person_properties:
                gathered_exprs.append(property_to_expr(p, team=self._team, scope="event"))

        queries: list[ast.SelectQuery] = []
        for expr in gathered_exprs:
            queries.append(self._select_from_events(select_expr, expr))

        negative_guard_query = self._negative_guard_query()
        if negative_guard_query:
            queries.append(negative_guard_query)

        return queries

    def get_queries_for_session_id_matching(self) -> list[ast.SelectQuery]:
        return self._get_queries_for_matching(
            select_expr=ast.Alias(alias="session_id", expr=ast.Field(chain=["$session_id"]))
        )

    def get_query_for_event_id_matching(self) -> ast.SelectQuery | ast.SelectSetQuery:
        select_queries: list[ast.SelectQuery] = self._get_queries_for_matching(
            select_expr=ast.Alias(alias="session_id", expr=ast.Field(chain=["$session_id"]))
        )
        select_exprs: list[ast.Expr] = []
        for q in select_queries:
            select_exprs.append(
                ast.CompareOperation(
                    # this hits the distributed events table from the distributed session_replay_events table
                    # so we should use GlobalIn
                    # see https://clickhouse.com/docs/en/sql-reference/operators/in#distributed-subqueries
                    op=ast.CompareOperationOp.GlobalIn,
                    left=ast.Field(chain=["s", "session_id"]),
                    right=q,
                )
            )
        return self._select_from_events(
            select_expr=ast.Call(name="groupUniqArray", args=[ast.Field(chain=["uuid"])]),
            where_expr=self.wrapped_with_query_operand(exprs=select_exprs),
        )

    def get_event_ids_for_session(self) -> SessionRecordingQueryResult:
        query = self.get_query_for_event_id_matching()

        hogql_query_response = execute_hogql_query(
            query=query,
            team=self._team,
            query_type="SessionRecordingMatchingEventsForSessionQuery",
            modifiers=self._hogql_query_modifiers,
        )

        flattened_results = [str(uuid) for row in hogql_query_response.results for uuid in row[0]]

        return SessionRecordingQueryResult(
            results=flattened_results,
            has_more_recording=False,
            timings=hogql_query_response.timings,
        )

    def _where_predicates(self, where_expr: ast.Expr | list[ast.Expr] | None) -> ast.Expr:
        exprs: list[ast.Expr] = [
            ast.Call(
                name="notEmpty",
                args=[ast.Field(chain=["$session_id"])],
            ),
            # regardless of any other filters limit between TTL and current time
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=datetime.now() - timedelta(days=self.ttl_days)),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Call(name="now", args=[]),
            ),
        ]

        if isinstance(where_expr, ast.Expr):
            exprs.append(where_expr)
        elif isinstance(where_expr, list):
            exprs += where_expr

        # TRICKY: we're adding a buffer to the date range to ensure we get all the events
        # you can start sending us events before the session starts
        if self._query.date_from:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    # TRICKY: technically you could start sending us events
                    # almost 24 hours before the session recording starts
                    # so we push the events date range a day earlier
                    right=ast.Constant(value=self.query_date_range.date_from() - timedelta(days=1)),
                )
            )

        # and the events can end almost 24 hours after the session recording ends
        # so we push the events date range a day later
        if self._query.date_to:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=self.query_date_range.date_to() + timedelta(days=1)),
                )
            )

        if self._query.session_ids:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["$session_id"]),
                    right=ast.Constant(value=self._query.session_ids),
                )
            )

        return ast.And(exprs=exprs)

    def _having_predicates(self) -> ast.Expr:
        exprs: list[ast.Expr] = []

        if self.event_properties:
            # when we're saying property is not set then we have to check it is not set on every event
            # e.g. countIf(JSONHas(events.properties, '$feature/target-flag')) = 0
            for prop in self.event_properties:
                if getattr(prop, "operator", None) in NEGATIVE_OPERATORS:
                    exprs.append(
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Call(
                                name="countIf",
                                args=[
                                    # we count the positive equivalent so we can easily assert there are no matches
                                    property_to_expr(
                                        prop.model_copy(update={"operator": INVERSE_OPERATOR_FOR[prop.operator]}),
                                        team=self._team,
                                        scope="event",
                                    ),
                                ],
                            ),
                            right=ast.Constant(value=0),
                        )
                    )

        return self.wrapped_with_query_operand(exprs=exprs) if exprs else ast.Constant(value=True)

    @property
    def action_entities(self):
        # TODO what do we send to the API instead to avoid needing to do this
        return [legacy_entity_to_node(Entity(e), True, MathAvailability.Unavailable) for e in self._query.actions or []]

    @property
    def event_entities(self):
        # TODO what do we send to the API instead to avoid needing to do this
        # TODO is this overkill since it feels like we only need a few things off the entity
        return [legacy_entity_to_node(Entity(e), True, MathAvailability.Unavailable) for e in self._query.events or []]

    @property
    def entities(self):
        return self.action_entities + self.event_entities

    @property
    def event_properties(self):
        return [g for g in (self._query.properties or []) if is_event_property(g)]

    @property
    def group_properties(self):
        return [g for g in (self._query.properties or []) if is_group_property(g)]

    @property
    def person_properties(self) -> list[AnyPropertyFilter] | None:
        return [g for g in (self._query.properties or []) if is_person_property(g)]

    def _negative_guard_query(self) -> ast.SelectQuery | None:
        if self._query.operand == "OR":
            return None

        gathered_exprs: list[ast.Expr] = []

        event_where_exprs = self._negative_event_predicates
        for expr in event_where_exprs:
            gathered_exprs.append(expr)

        for p in self.event_properties:
            # TODO how can we detect negative queries
            if "operator" in p and p.operator in NEGATIVE_OPERATORS:
                gathered_exprs.append(
                    property_to_expr(
                        p,
                        team=self._team,
                        scope="replay",
                    )
                )

        for p in self.group_properties:
            if p.operator in NEGATIVE_OPERATORS:
                gathered_exprs.append(property_to_expr(p, team=self._team))

        if self._team.person_on_events_mode and self.person_properties:
            for p in self.person_properties:
                # need a solution here for HogQL property filters
                if "operator" in p and p.operator in NEGATIVE_OPERATORS:
                    gathered_exprs.append(property_to_expr(p, team=self._team, scope="event"))

        if gathered_exprs:
            return self._select_from_events(
                select_expr=ast.Alias(alias="session_id", expr=ast.Field(chain=["$session_id"])),
                where_expr=gathered_exprs,
            )
        else:
            return None
