from collections.abc import Iterable
from datetime import timedelta
from typing import Optional, cast

import posthoganalytics

from posthog.schema import (
    ActionsNode,
    DataWarehouseNode,
    EventPropertyFilter,
    EventsNode,
    HogQLQueryModifiers,
    PropertyOperator,
    RecordingsQuery,
)

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query, tracer

from posthog.clickhouse.query_tagging import Product, tag_queries
from posthog.hogql_queries.legacy_compatibility.filter_to_query import MathAvailability, legacy_entity_to_node
from posthog.models import Entity, EventProperty, Team
from posthog.session_recordings.queries.sub_queries.base_query import SessionRecordingsListingBaseQuery
from posthog.session_recordings.queries.utils import (
    INVERSE_OPERATOR_FOR,
    NEGATIVE_OPERATORS,
    SessionRecordingQueryResult,
    _entity_to_expr,
    is_event_property,
    is_group_property,
    is_person_property,
)
from posthog.types import AnyPropertyFilter

# Person properties eligible for hybrid query optimization
# These are high-selectivity identity properties where the three-stage query provides value
HYBRID_QUERY_ELIGIBLE_PROPERTIES = {
    "email",
    "name",
    "username",
    "user_id",
    "external_id",
    "distinct_id",
}


def get_negative_entity_properties(
    entities: list[EventsNode | ActionsNode | DataWarehouseNode | str],
) -> list[AnyPropertyFilter]:
    negative_props: list[AnyPropertyFilter] = []
    for entity in entities:
        if isinstance(entity, DataWarehouseNode | str) or not entity.properties:
            continue
        for prop in entity.properties:
            if is_negative_prop(prop):
                negative_props.append(prop)
    return negative_props


def is_negative_prop(prop: AnyPropertyFilter) -> bool:
    return hasattr(prop, "operator") and prop.operator in NEGATIVE_OPERATORS


class ReplayFiltersEventsSubQuery(SessionRecordingsListingBaseQuery):
    def __init__(
        self,
        team: Team,
        query: RecordingsQuery,
        allow_event_property_expansion: bool = False,
        hogql_query_modifiers: Optional[HogQLQueryModifiers] = None,
    ):
        super().__init__(team, query)
        self._hogql_query_modifiers = hogql_query_modifiers
        self._allow_event_property_expansion = allow_event_property_expansion

    @staticmethod
    def _event_predicates(
        entities: Iterable[EventsNode | ActionsNode | DataWarehouseNode | str], team: Team
    ) -> list[ast.Expr]:
        event_exprs: list[ast.Expr] = []

        for entity in entities:
            if isinstance(entity, DataWarehouseNode | str):
                continue

            # this is always _positive_ operations
            entity_exprs = [_entity_to_expr(entity=entity)]

            if entity.properties:
                entity_exprs.append(property_to_expr(entity.properties, team=team, scope="replay_entity"))

            event_exprs.append(ast.And(exprs=entity_exprs))

        return event_exprs

    def _select_from_events(
        self,
        select_expr: ast.Expr | list[ast.Expr],
        where_expr: ast.Expr | list[ast.Expr],
        group_by: list[ast.Expr],
        limit_expr: ast.Expr,
    ) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=select_expr if isinstance(select_expr, list) else [select_expr],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"]),
            ),
            where=self._where_predicates(where_expr),
            having=self._having_predicates(),
            group_by=group_by,
            order_by=[ast.OrderExpr(expr=ast.Call(name="min", args=[ast.Field(chain=["timestamp"])]), order="DESC")],
            limit=limit_expr,
        )

    def _is_hybrid_query_mode_enabled(self) -> bool:
        """
        Hybrid mode uses a three-stage query to find all sessions for persons matching properties,
        including sessions from before the person was identified.

        This solves the "late identification problem" where filtering by person properties
        in standard PoE mode only finds sessions where those properties existed at event time.
        """
        return posthoganalytics.feature_enabled(
            "enable-hybrid-poe-replay-filtering",
            str(self._team.id),
            send_feature_flag_events=False,
        )

    def _should_use_hybrid_query(self, person_properties: list) -> bool:
        """
        Determine if hybrid query is appropriate for the given person properties.

        Returns:
            True if at least one property is in the allowlist and feature flag is enabled
        """
        if not self._is_hybrid_query_mode_enabled():
            return False

        # Don't use hybrid query if there are negative operators
        # Negative operators (IS_NOT, NOT_ICONTAINS, etc.) would match too many people
        # For example, "email doesn't contain @company.com" matches almost everyone
        # This would load 100-1000 random people and miss the actual recordings we want
        for prop in person_properties:
            if is_negative_prop(prop):
                return False

        # Check if at least one property is eligible for hybrid query
        for prop in person_properties:
            if hasattr(prop, "key") and prop.key in HYBRID_QUERY_ELIGIBLE_PROPERTIES:
                return True

        return False

    def _build_persons_query(
        self,
        person_properties: list,
        person_id_limit: int,
    ) -> ast.SelectQuery:
        """
        Stage 1: Build query to find person_ids from persons table.

        Returns:
            SelectQuery that finds person_ids matching the property filters
        """
        # Build person property filter expression
        person_filter_expr = property_to_expr(
            person_properties,
            team=self._team,
            scope="person",
        )

        # Query persons table directly
        return ast.SelectQuery(
            select=[ast.Alias(alias="person_id", expr=ast.Field(chain=["id"]))],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
            where=person_filter_expr,
            limit=ast.Constant(value=person_id_limit),
        )

    def _build_distinct_ids_query(
        self,
        persons_subquery: ast.SelectQuery,
    ) -> ast.SelectQuery:
        """
        Stage 2: Build query to find all distinct_ids for the person_ids from Stage 1.

        This expands from person_ids to all distinct_ids associated with those persons,
        including distinct_ids from before the person was identified.

        Args:
            persons_subquery: The query from Stage 1 that returns person_ids

        Returns:
            SelectQuery that finds all distinct_ids for those person_ids
        """
        return ast.SelectQuery(
            select=[ast.Field(chain=["distinct_id"])],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["person_distinct_ids"])  # HogQL virtual table
            ),
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["person_id"]),
                right=persons_subquery,  # Nested subquery
            ),
        )

    def _build_sessions_query(
        self,
        distinct_ids_subquery: ast.SelectQuery,
    ) -> ast.SelectQuery:
        """
        Stage 3: Build query to find all sessions for the distinct_ids from Stage 2.

        This finds all session_ids from events where the distinct_id matches any of
        the distinct_ids from Stage 2, within the query date range (with buffers).

        Args:
            distinct_ids_subquery: The query from Stage 2 that returns distinct_ids

        Returns:
            SelectQuery that finds all session_ids for those distinct_ids
        """
        # Calculate date range with ±1 day buffer to match events_subquery behavior
        # Events can arrive before session starts or after it ends
        date_from_buffered = self.query_date_range.date_from() - timedelta(days=1)
        date_to_buffered = self.query_date_range.date_to() + timedelta(days=1)

        return ast.SelectQuery(
            select=[ast.Alias(alias="session_id", expr=ast.Field(chain=["$session_id"]))],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["team_id"]),
                        right=ast.Constant(value=self._team.pk),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=ast.Field(chain=["distinct_id"]),
                        right=distinct_ids_subquery,
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=ast.Field(chain=["timestamp"]),
                        right=ast.Constant(value=date_from_buffered),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.LtEq,
                        left=ast.Field(chain=["timestamp"]),
                        right=ast.Constant(value=date_to_buffered),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.NotEq,
                        left=ast.Call(name="empty", args=[ast.Field(chain=["$session_id"])]),
                        right=ast.Constant(value=1),
                    ),
                ]
            ),
            group_by=[ast.Field(chain=["$session_id"])],  # DISTINCT session_id
            limit=ast.Constant(value=1000000),
        )

    def _get_person_id_based_sessions_query(
        self,
        person_properties: list,
    ) -> ast.SelectQuery:
        """
        Build three-stage hybrid query for person properties in PoE mode.

        This is the Pure AST implementation that:
        1. Queries persons table for person_ids (Phase 1 optimization - 100x faster)
        2. Finds all distinct_ids for those person_ids
        3. Finds all sessions for those distinct_ids

        The three-stage approach ensures we find ALL sessions for a person,
        including sessions from before they were identified (solves late identification problem).

        Example timeline:
            Day 1: User browses anonymously → session "abc" with distinct_id "anon123"
            Day 3: User signs up with email → person gets email property, merges with "anon123"

            Standard PoE: Filtering by email only finds Day 3+ sessions
            Hybrid query: Finds ALL sessions (Day 1+) because we find all distinct_ids for the person

        Returns:
            SelectQuery that returns session_ids for persons matching the properties
        """
        # Detect if we're using fuzzy operators that might match many people
        has_fuzzy_operators = False
        for prop in person_properties:
            if hasattr(prop, "operator") and prop.operator in [
                PropertyOperator.ICONTAINS,
                PropertyOperator.NOT_ICONTAINS,
                PropertyOperator.REGEX,
                PropertyOperator.NOT_REGEX,
                PropertyOperator.IS_SET,
                PropertyOperator.IS_NOT_SET,
            ]:
                has_fuzzy_operators = True
                break

        # Exact operators (email="user@example.com") typically match 1-10 people
        # Fuzzy operators (email icontains "gmail") might match thousands
        person_id_limit = 1000 if has_fuzzy_operators else 100

        # Track hybrid query usage for monitoring
        try:
            from opentelemetry import trace

            property_keys = [p.key if hasattr(p, "key") else "unknown" for p in person_properties]
            operators = [str(p.operator) if hasattr(p, "operator") else "unknown" for p in person_properties]

            # Check which properties are in the allowlist
            eligible_properties = [
                p.key for p in person_properties if hasattr(p, "key") and p.key in HYBRID_QUERY_ELIGIBLE_PROPERTIES
            ]
            ineligible_properties = [
                p.key for p in person_properties if hasattr(p, "key") and p.key not in HYBRID_QUERY_ELIGIBLE_PROPERTIES
            ]

            posthoganalytics.capture(
                distinct_id=str(self._team.id),
                event="hybrid_poe_replay_query_executed",
                properties={
                    "team_id": self._team.id,
                    "property_count": len(person_properties),
                    "property_keys": property_keys,
                    "eligible_property_keys": eligible_properties,
                    "ineligible_property_keys": ineligible_properties,
                    "operators": operators,
                    "has_fuzzy_operators": has_fuzzy_operators,
                    "person_id_limit": person_id_limit,
                    "date_range_days": (self.query_date_range.date_to() - self.query_date_range.date_from()).days,
                    "$feature/hybrid-poe-replay-filtering": True,
                },
            )

            # Add OpenTelemetry span attributes for tracing
            span = trace.get_current_span()
            if span:
                span.set_attribute("replay.hybrid_query.property_count", len(person_properties))
                span.set_attribute("replay.hybrid_query.eligible_property_count", len(eligible_properties))
                span.set_attribute("replay.hybrid_query.has_fuzzy_operators", has_fuzzy_operators)
                span.set_attribute("replay.hybrid_query.person_id_limit", person_id_limit)

        except Exception as e:
            posthoganalytics.capture_exception(e, properties={"context": "hybrid_query_monitoring"})

        # Build the three-stage query using Pure AST
        # Stage 1: Find person_ids from persons table
        persons_query = self._build_persons_query(person_properties, person_id_limit)

        # Stage 2: Find distinct_ids for those person_ids
        distinct_ids_query = self._build_distinct_ids_query(persons_query)

        # Stage 3: Find sessions for those distinct_ids
        sessions_query = self._build_sessions_query(distinct_ids_query)

        return sessions_query

    def _get_queries_for_matching(self, select_expr: ast.Expr, group_by: list[ast.Expr]) -> list[ast.SelectQuery]:
        """
        takes each filter in the query that can be queried from the events table
        and makes a separate query for each
        this might be slower than the previous approach of having one huge event query
        but that approach is horribly complex, and we keep getting bug reports
        that are avoidable with a simpler approach
        """
        gathered_exprs: list[ast.Expr] = []
        event_where_exprs = self._event_predicates(self.entities, self._team)
        if event_where_exprs:
            gathered_exprs += event_where_exprs

        # Skip event properties with negative operators since they're handled by _negative_guard_query
        skip_negative_properties = self._query.operand == "AND"

        for p in self.event_properties:
            if skip_negative_properties and is_negative_prop(p):
                continue

            if self._allow_event_property_expansion:
                events_seen_with_this_property, property_expr = self.with_team_events_added(p, self._team)
                gathered_exprs.append(
                    ast.And(
                        # we can include with the property the events it was seen with
                        # this should recruit the table's order by and speeed things up
                        exprs=[
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.In,
                                left=ast.Field(chain=["events", "event"]),
                                # sort them only so the snapshot tests don't flap
                                right=ast.Constant(value=sorted(events_seen_with_this_property)),
                            ),
                            property_expr,
                        ]
                    )
                    if events_seen_with_this_property
                    else property_expr
                )
            else:
                gathered_exprs.append(
                    property_to_expr(
                        p,
                        team=self._team,
                        scope="replay",
                    )
                )

        for p in self.group_properties:
            if skip_negative_properties and is_negative_prop(p):
                continue
            gathered_exprs.append(property_to_expr(p, team=self._team))

        # Handle person properties with hybrid query mode if enabled and appropriate
        hybrid_query: Optional[ast.SelectQuery] = None
        if self._team.person_on_events_mode and self.person_properties:
            if self._should_use_hybrid_query(self.person_properties):
                hybrid_query = self._get_person_id_based_sessions_query(self.person_properties)
                # Don't add person properties to gathered_exprs - we've handled them via hybrid query
            else:
                # Use standard PoE approach (fast but potentially incomplete)
                # Used for all non-identity properties or when feature flag is off
                for p in self.person_properties:
                    if skip_negative_properties and is_negative_prop(p):
                        continue
                    gathered_exprs.append(property_to_expr(p, team=self._team, scope="event"))

        queries: list[ast.SelectQuery] = []

        # Add hybrid query first if we used it for person properties
        if hybrid_query:
            queries.append(hybrid_query)
        for expr in gathered_exprs:
            # Increased LIMIT from 10000 to 1000000 to handle cases where:
            # 1. Session recording sampling is enabled (only small % of sessions have recordings)
            # 2. Replay was recently disabled (recent sessions have no recordings)
            # With the original 10000 limit, we might miss all sessions that actually have recordings.
            queries.append(
                self._select_from_events(select_expr, expr, group_by=group_by, limit_expr=ast.Constant(value=1000000))
            )

        negative_guard_query = self._negative_guard_query()
        if negative_guard_query:
            queries.append(negative_guard_query)

        return queries

    def get_queries_for_session_id_matching(self) -> list[ast.SelectQuery]:
        return self._get_queries_for_matching(
            select_expr=ast.Alias(alias="session_id", expr=ast.Field(chain=["$session_id"])),
            group_by=[ast.Field(chain=["$session_id"])],
        )

    def get_query_for_event_id_matching(self) -> ast.SelectQuery | ast.SelectSetQuery:
        # Subqueries only need to return uuid for the GlobalIn comparison
        select_queries: list[ast.SelectQuery] = self._get_queries_for_matching(
            select_expr=ast.Field(chain=["uuid"]),
            # when matching we want to select flag lists of event UUIds so we group by session_id, and then uuid
            group_by=[ast.Field(chain=["$session_id"]), ast.Field(chain=["uuid"])],
        )
        select_exprs: list[ast.Expr] = []
        for q in select_queries:
            select_exprs.append(
                ast.CompareOperation(
                    # this hits the distributed events table from the distributed events table
                    # so we should use GlobalIn
                    # see https://clickhouse.com/docs/en/sql-reference/operators/in#distributed-subqueries
                    op=ast.CompareOperationOp.GlobalIn,
                    left=ast.Field(chain=["uuid"]),
                    right=q,
                )
            )
        return self._select_from_events(
            select_expr=[ast.Field(chain=["uuid"]), ast.Call(name="any", args=[ast.Field(chain=["timestamp"])])],
            where_expr=self.wrapped_with_query_operand(exprs=select_exprs),
            # when matching we want to select flag lists of event UUIds so we group by session_id, and then uuid
            group_by=[ast.Field(chain=["$session_id"]), ast.Field(chain=["uuid"])],
            limit_expr=ast.Constant(value=10000),
        )

    def get_event_ids_for_session(self) -> SessionRecordingQueryResult:
        query = self.get_query_for_event_id_matching()

        tag_queries(product=Product.REPLAY, team_id=self._team.id)
        hogql_query_response = execute_hogql_query(
            query=query,
            team=self._team,
            query_type="SessionRecordingMatchingEventsForSessionQuery",
            modifiers=self._hogql_query_modifiers,
        )

        return SessionRecordingQueryResult(
            results=hogql_query_response.results,
            has_more_recording=False,
            timings=hogql_query_response.timings,
        )

    def _where_predicates(self, where_expr: ast.Expr | list[ast.Expr] | None) -> ast.Expr:
        exprs: list[ast.Expr] = [
            ast.Call(
                name="notEmpty",
                args=[ast.Field(chain=["$session_id"])],
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
        if self._query.operand == "OR":
            return ast.Constant(value=True)

        def countif_zero(prop: AnyPropertyFilter) -> ast.Expr:
            operator = cast(PropertyOperator, prop.operator)  # type: ignore[union-attr]
            inverted = prop.model_copy(update={"operator": INVERSE_OPERATOR_FOR[operator]})
            return ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Call(name="countIf", args=[property_to_expr(inverted, team=self._team, scope="event")]),
                right=ast.Constant(value=0),
            )

        negative_props = [p for p in self.event_properties if is_negative_prop(p)]
        negative_props += get_negative_entity_properties(self.entities)
        negative_props += [p for p in self.group_properties if is_negative_prop(p)]
        if self._team.person_on_events_mode and self.person_properties:
            negative_props += [p for p in self.person_properties if is_negative_prop(p)]

        exprs = [countif_zero(p) for p in negative_props]
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

    def _has_negative_properties(self) -> bool:
        if any(is_negative_prop(p) for p in self.event_properties):
            return True
        if get_negative_entity_properties(self.entities):
            return True
        if any(is_negative_prop(p) for p in self.group_properties):
            return True
        if self._team.person_on_events_mode and self.person_properties:
            if any(is_negative_prop(p) for p in self.person_properties):
                return True
        return False

    def _negative_guard_query(self) -> ast.SelectQuery | None:
        if self._query.operand == "OR":
            return None

        if not self._has_negative_properties():
            return None

        return self._select_from_events(
            select_expr=ast.Alias(alias="session_id", expr=ast.Field(chain=["$session_id"])),
            where_expr=[],
            group_by=[ast.Field(chain=["$session_id"])],
            limit_expr=ast.Constant(value=1000000),
        )

    @staticmethod
    @tracer.start_as_current_span("ReplayFiltersEventsSubQuery.with_team_events_added")
    def with_team_events_added(p: AnyPropertyFilter, team: Team) -> tuple[list[str], ast.Expr]:
        """
        We support property only filters because users expect it, but unlike insights
        we don't have event series to help us hit the good-spot of an events table query
        and these can get slow fast.
        this should be fixed elsewhere but in the short term,
        we can load the events for a given property from postgres and return the event properties used and the property expression
        """
        try:
            if not isinstance(p, EventPropertyFilter):
                # something unexpected has been passed to us,
                # but we would always have called property_to_expr before
                # so let's just do that
                return [], property_to_expr(p, team=team, scope="replay")

            events_that_have_the_property: list[str] = list(
                EventProperty.objects.filter(team_id=team.id, property=p.key).values_list("event", flat=True)
            )

            return events_that_have_the_property, property_to_expr(p, team=team, scope="replay")
        except Exception as e:
            posthoganalytics.capture_exception(e, properties={"replay_feature": "with_team_events_added"})
            # we can return this transformation here because this is what was always run in the past
            # so if _that_ is going to fail nothing this method can do could change it
            return [], property_to_expr(p, team=team, scope="replay")
