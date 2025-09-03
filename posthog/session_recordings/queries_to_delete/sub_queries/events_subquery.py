from datetime import datetime, timedelta
from typing import Optional

from posthog.constants import PropertyOperatorType
from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.legacy_compatibility.filter_to_query import legacy_entity_to_node, MathAvailability
from posthog.models import Team, Action, Entity
from posthog.schema import (
    RecordingsQuery,
    HogQLQueryModifiers,
    NodeKind,
    PropertyGroupFilterValue,
    FilterLogicalOperator,
)
from posthog.session_recordings.queries_to_delete.sub_queries.base_query import SessionRecordingsListingBaseQuery
from posthog.session_recordings.queries_to_delete.utils import (
    INVERSE_OPERATOR_FOR,
    NEGATIVE_OPERATORS,
    SessionRecordingQueryResult,
    _entity_to_expr,
    is_event_property,
    is_group_property,
    is_person_property,
    poe_is_active,
)


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
    def _event_predicates(self):
        event_exprs: list[ast.Expr] = []
        event_names: set[int | str] = set()

        for entity in self.entities:
            if entity.kind == NodeKind.ACTIONS_NODE:
                action = Action.objects.get(pk=int(entity.id), team__project_id=self._team.project_id)
                event_names.update([ae for ae in action.get_step_events() if ae and ae not in event_names])
            else:
                if entity.event and entity.event not in event_names:
                    event_names.add(entity.event)

            entity_exprs = [_entity_to_expr(entity=entity)]

            if entity.properties:
                entity_exprs.append(property_to_expr(entity.properties, team=self._team, scope="replay_entity"))

            event_exprs.append(ast.And(exprs=entity_exprs))

        return event_exprs, list(event_names)

    def _select_from_events(self, select_expr: ast.Expr) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=[select_expr],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"]),
            ),
            where=self._where_predicates(),
            having=self._having_predicates(),
            group_by=[ast.Field(chain=["$session_id"])],
            order_by=[ast.OrderExpr(expr=ast.Call(name="min", args=[ast.Field(chain=["timestamp"])]), order="DESC")],
        )

    def get_query_for_session_id_matching(self) -> ast.SelectQuery | ast.SelectSetQuery | None:
        use_poe = poe_is_active(self._team) and self.person_properties

        if self.entities or self.event_properties or self.group_properties or use_poe:
            return self._select_from_events(ast.Alias(alias="session_id", expr=ast.Field(chain=["$session_id"])))
        else:
            return None

    def get_query_for_event_id_matching(self) -> ast.SelectQuery | ast.SelectSetQuery:
        return self._select_from_events(ast.Call(name="groupUniqArray", args=[ast.Field(chain=["uuid"])]))

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

    def _where_predicates(self) -> ast.Expr:
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

        (event_where_exprs, _) = self._event_predicates
        if event_where_exprs:
            # we OR all events in the where and use hasAll / hasAny in the HAVING clause
            exprs.append(ast.Or(exprs=event_where_exprs))

        if self.event_properties:
            # we only query positive properties here, since negative properties we need to query over the session
            exprs.append(
                property_to_expr(
                    [
                        p
                        for p in self.event_properties
                        if getattr(p, "operator", None) is None or p.operator not in NEGATIVE_OPERATORS
                    ],
                    team=self._team,
                    scope="replay",
                )
            )

        if self.group_properties:
            exprs.append(property_to_expr(self.group_properties, team=self._team))

        if self._team.person_on_events_mode and self.person_properties:
            exprs.append(property_to_expr(self.person_properties, team=self._team, scope="event"))

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
        (_, event_names) = self._event_predicates

        exprs: list[ast.Expr] = []
        if event_names:
            exprs.append(
                ast.Call(
                    name="hasAll" if self.property_operand == PropertyOperatorType.AND else "hasAny",
                    args=[
                        ast.Call(name="groupUniqArray", args=[ast.Field(chain=["event"])]),
                        # KLUDGE: sorting only so that snapshot tests are consistent
                        ast.Constant(value=sorted(event_names)),
                    ],
                )
            )

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

        if exprs:
            return self.ast_operand(exprs=exprs)
        else:
            return ast.Constant(value=True)

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
    def person_properties(self) -> PropertyGroupFilterValue | None:
        person_property_groups = [g for g in (self._query.properties or []) if is_person_property(g)]
        return (
            PropertyGroupFilterValue(
                type=FilterLogicalOperator.AND_ if self.property_operand == "AND" else FilterLogicalOperator.OR_,
                values=person_property_groups,
            )
            if person_property_groups
            else None
        )
