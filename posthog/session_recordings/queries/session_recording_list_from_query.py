import re
from typing import Any, NamedTuple, cast, Optional, Union
from datetime import datetime, timedelta, UTC

import posthoganalytics

from posthog.constants import PropertyOperatorType
from posthog.hogql import ast
from posthog.hogql.ast import CompareOperation
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr, action_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.legacy_compatibility.filter_to_query import MathAvailability, legacy_entity_to_node
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team, Entity, Action
from posthog.schema import (
    QueryTiming,
    HogQLQueryModifiers,
    PersonsOnEventsMode,
    RecordingsQuery,
    DateRange,
    NodeKind,
    EventsNode,
    ActionsNode,
    PropertyGroupFilterValue,
    FilterLogicalOperator,
    RecordingOrder,
    PersonPropertyFilter,
    EventPropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    PropertyOperator,
    CohortPropertyFilter,
)
from posthog.session_recordings.queries.session_replay_events import ttl_days

import structlog

from posthog.types import AnyPropertyFilter

logger = structlog.get_logger(__name__)

NEGATIVE_OPERATORS = [
    PropertyOperator.IS_NOT_SET,
    PropertyOperator.IS_NOT,
    PropertyOperator.NOT_REGEX,
    PropertyOperator.NOT_ICONTAINS,
    # PropertyOperator.NOT_BETWEEN, # in the schema but not used anywhere
    # PropertyOperator.NOT_IN,  # COHORT operator we don't need to handle it explicitly
]

INVERSE_OPERATOR_FOR = {
    PropertyOperator.IS_NOT_SET: PropertyOperator.IS_SET,
    PropertyOperator.IS_NOT: PropertyOperator.EXACT,
    PropertyOperator.NOT_IN: PropertyOperator.IN_,
    PropertyOperator.NOT_REGEX: PropertyOperator.REGEX,
    PropertyOperator.NOT_ICONTAINS: PropertyOperator.ICONTAINS,
    PropertyOperator.NOT_BETWEEN: PropertyOperator.BETWEEN,
}


def is_event_property(p: AnyPropertyFilter) -> bool:
    p_type = getattr(p, "type", None)
    p_key = getattr(p, "key", "")
    return p_type == "event" or (p_type == "hogql" and bool(re.search(r"(?<!person\.)properties\.", p_key)))


def is_person_property(p: AnyPropertyFilter) -> bool:
    p_type = getattr(p, "type", None)
    p_key = getattr(p, "key", "")
    return p_type == "person" or (p_type == "hogql" and "person.properties" in p_key)


def is_group_property(p: AnyPropertyFilter) -> bool:
    p_type = getattr(p, "type", None)
    return p_type == "group"


def is_cohort_property(p: AnyPropertyFilter) -> bool:
    p_type = getattr(p, "type", None)
    return bool(p_type and "cohort" in p_type)


def expand_test_account_filters(team: Team) -> list[AnyPropertyFilter]:
    prop_filters: list[AnyPropertyFilter] = []
    for prop in team.test_account_filters:
        match prop.get("type", None):
            case "person":
                prop_filters.append(PersonPropertyFilter(**prop))
            case "event":
                prop_filters.append(EventPropertyFilter(**prop))
            case "group":
                prop_filters.append(GroupPropertyFilter(**prop))
            case "hogql":
                prop_filters.append(HogQLPropertyFilter(**prop))
            case "cohort":
                prop_filters.append(CohortPropertyFilter(**prop))
            case None:
                logger.warn("test account filter had no type", filter=prop)
                prop_filters.append(EventPropertyFilter(**prop))

    return prop_filters


class SessionRecordingQueryResult(NamedTuple):
    results: list
    has_more_recording: bool
    timings: list[QueryTiming] | None = None


class UnexpectedQueryProperties(Exception):
    def __init__(self, remaining_properties: list[AnyPropertyFilter] | None):
        self.remaining_properties = remaining_properties
        super().__init__(f"Unexpected properties in query: {remaining_properties}")


def _strip_person_and_event_and_cohort_properties(
    properties: list[AnyPropertyFilter] | None,
) -> list[AnyPropertyFilter] | None:
    if not properties:
        return None

    properties_to_keep = [
        p
        for p in properties
        if not is_event_property(p)
        and not is_person_property(p)
        and not is_group_property(p)
        and not is_cohort_property(p)
    ]

    return properties_to_keep


class SessionRecordingsListingBaseQuery:
    _team: Team
    _query: RecordingsQuery

    def __init__(self, team: Team, query: RecordingsQuery):
        self._team = team
        self._query = query

    @property
    def ttl_days(self):
        return ttl_days(self._team)

    @property
    def property_operand(self):
        return PropertyOperatorType.AND if self._query.operand == "AND" else PropertyOperatorType.OR

    @property
    def ast_operand(self) -> type[Union[ast.And, ast.Or]]:
        return ast.And if self.property_operand == "AND" else ast.Or

    @property
    def query_date_range(self):
        return QueryDateRange(
            date_range=DateRange(date_from=self._query.date_from, date_to=self._query.date_to, explicitDate=True),
            team=self._team,
            interval=None,
            now=datetime.now(),
        )


class SessionRecordingListFromQuery(SessionRecordingsListingBaseQuery):
    SESSION_RECORDINGS_DEFAULT_LIMIT = 50

    _team: Team
    _query: RecordingsQuery

    BASE_QUERY: str = """
        SELECT s.session_id,
            any(s.team_id),
            any(s.distinct_id),
            min(s.min_first_timestamp) as start_time,
            max(s.max_last_timestamp) as end_time,
            dateDiff('SECOND', start_time, end_time) as duration,
            argMinMerge(s.first_url) as first_url,
            sum(s.click_count) as click_count,
            sum(s.keypress_count) as keypress_count,
            sum(s.mouse_activity_count) as mouse_activity_count,
            sum(s.active_milliseconds)/1000 as active_seconds,
            (duration - active_seconds) as inactive_seconds,
            sum(s.console_log_count) as console_log_count,
            sum(s.console_warn_count) as console_warn_count,
            sum(s.console_error_count) as console_error_count,
            {ongoing_selection},
            round((
            ((sum(s.active_milliseconds) / 1000 + sum(s.click_count) + sum(s.keypress_count) + sum(s.console_error_count))) -- intent
            /
            ((sum(s.mouse_activity_count) + dateDiff('SECOND', start_time, end_time) + sum(s.console_error_count) + sum(s.console_log_count) + sum(s.console_warn_count)))
            * 100
            ), 2) as activity_score
        FROM raw_session_replay_events s
        WHERE {where_predicates}
        GROUP BY session_id
        HAVING {having_predicates}
        ORDER BY {order_by} DESC
        """

    @staticmethod
    def _data_to_return(results: list[Any] | None) -> list[dict[str, Any]]:
        default_columns = [
            "session_id",
            "team_id",
            "distinct_id",
            "start_time",
            "end_time",
            "duration",
            "first_url",
            "click_count",
            "keypress_count",
            "mouse_activity_count",
            "active_seconds",
            "inactive_seconds",
            "console_log_count",
            "console_warn_count",
            "console_error_count",
            "ongoing",
            "activity_score",
        ]

        return [
            {
                **dict(zip(default_columns, row[: len(default_columns)])),
            }
            for row in results or []
        ]

    def __init__(
        self,
        team: Team,
        query: RecordingsQuery,
        hogql_query_modifiers: Optional[HogQLQueryModifiers],
        **_,
    ):
        # TRICKY: we need to make sure we init test account filters only once,
        # otherwise we'll end up with a lot of duplicated test account filters in the query
        query = query.model_copy(deep=True)
        if query.filter_test_accounts:
            query.properties = expand_test_account_filters(team) + (query.properties or [])

        super().__init__(team, query)

        self._paginator = HogQLHasMorePaginator(
            limit=query.limit or self.SESSION_RECORDINGS_DEFAULT_LIMIT, offset=query.offset or 0
        )
        self._hogql_query_modifiers = hogql_query_modifiers

    def run(self) -> SessionRecordingQueryResult:
        query = self.get_query()

        paginated_response = self._paginator.execute_hogql_query(
            # TODO I guess the paginator needs to know how to handle union queries or all callers are supposed to collapse them or .... 🤷
            query=cast(ast.SelectQuery, query),
            team=self._team,
            query_type="SessionRecordingListQuery",
            modifiers=self._hogql_query_modifiers,
            settings=HogQLGlobalSettings(allow_experimental_analyzer=False),  # This needs to be turned on eventually
        )

        return SessionRecordingQueryResult(
            results=(self._data_to_return(self._paginator.results)),
            has_more_recording=self._paginator.has_more(),
            timings=paginated_response.timings,
        )

    def get_query(self):
        return parse_select(
            self.BASE_QUERY,
            {
                # Check if the most recent _timestamp is within five minutes of the current time
                # proxy for a live session
                "ongoing_selection": ast.Alias(
                    alias="ongoing",
                    expr=ast.CompareOperation(
                        left=ast.Call(name="max", args=[ast.Field(chain=["s", "_timestamp"])]),
                        right=ast.Constant(
                            # provided in a placeholder, so we can pass now from python to make tests easier 🙈
                            value=datetime.now(UTC) - timedelta(minutes=5),
                        ),
                        op=ast.CompareOperationOp.GtEq,
                    ),
                ),
                "order_by": self._order_by_clause(),
                "where_predicates": self._where_predicates(),
                "having_predicates": self._having_predicates() or ast.Constant(value=True),
            },
        )

    def _order_by_clause(self) -> ast.Field:
        # KLUDGE: we only need a default here because mypy is silly
        order_by = self._query.order.value if self._query.order else RecordingOrder.START_TIME
        return ast.Field(chain=[order_by])

    def _where_predicates(self) -> Union[ast.And, ast.Or]:
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["s", "min_first_timestamp"]),
                right=ast.Constant(value=datetime.now(UTC) - timedelta(days=self.ttl_days)),
            )
        ]

        if self._query.distinct_ids:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["distinct_id"]),
                    right=ast.Constant(value=self._query.distinct_ids),
                )
            )
        else:
            person_id_compare_operation = PersonsIdCompareOperation(self._team, self._query).get_operation()
            if person_id_compare_operation:
                exprs.append(person_id_compare_operation)

        # we check for session_ids type not for truthiness since we want to allow empty lists
        if isinstance(self._query.session_ids, list):
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["session_id"]),
                    right=ast.Constant(value=self._query.session_ids),
                )
            )

        query_date_from = self.query_date_range.date_from()
        if query_date_from:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["s", "min_first_timestamp"]),
                    right=ast.Constant(value=query_date_from),
                )
            )

        query_date_to = self.query_date_range.date_to()
        if query_date_to:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["s", "min_first_timestamp"]),
                    right=ast.Constant(value=query_date_to),
                )
            )

        optional_exprs: list[ast.Expr] = []

        # if in PoE mode then we should be pushing person property queries into here
        events_sub_query = ReplayFiltersEventsSubQuery(self._team, self._query).get_query_for_session_id_matching()
        if events_sub_query:
            optional_exprs.append(
                ast.CompareOperation(
                    # this hits the distributed events table from the distributed session_replay_events table
                    # so we should use GlobalIn
                    # see https://clickhouse.com/docs/en/sql-reference/operators/in#distributed-subqueries
                    op=ast.CompareOperationOp.GlobalIn,
                    left=ast.Field(chain=["s", "session_id"]),
                    right=events_sub_query,
                )
            )

        # we want to avoid a join to persons since we don't ever need to select from them,
        # so we create our own persons sub query here
        # if PoE mode is on then this will be handled in the events subquery, and we don't need to do anything here
        person_subquery = PersonsPropertiesSubQuery(self._team, self._query).get_query()
        if person_subquery:
            optional_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["s", "distinct_id"]),
                    right=person_subquery,
                )
            )

        cohort_subquery = CohortPropertyGroupsSubQuery(self._team, self._query).get_query()
        if cohort_subquery:
            optional_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["s", "distinct_id"]),
                    right=cohort_subquery,
                )
            )

        remaining_properties = _strip_person_and_event_and_cohort_properties(self._query.properties)
        if remaining_properties:
            posthoganalytics.capture_exception(UnexpectedQueryProperties(remaining_properties))
            optional_exprs.append(property_to_expr(remaining_properties, team=self._team, scope="replay"))

        if self._query.console_log_filters:
            console_logs_subquery = ast.SelectQuery(
                select=[ast.Field(chain=["log_source_id"])],
                select_from=ast.JoinExpr(table=ast.Field(chain=["console_logs_log_entries"])),
                where=property_to_expr(
                    # convert to a property group so we can insert the correct operand
                    PropertyGroupFilterValue(
                        type=FilterLogicalOperator.AND_
                        if self.property_operand == "AND"
                        else FilterLogicalOperator.OR_,
                        values=self._query.console_log_filters,
                    ),
                    team=self._team,
                ),
            )

            optional_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["session_id"]),
                    right=console_logs_subquery,
                )
            )

        if optional_exprs:
            exprs.append(self.ast_operand(exprs=optional_exprs))

        return ast.And(exprs=exprs)

    def _having_predicates(self) -> ast.Expr | None:
        return (
            property_to_expr(self._query.having_predicates, team=self._team, scope="replay")
            if self._query.having_predicates
            else None
        )


def poe_is_active(team: Team) -> bool:
    return team.person_on_events_mode is not None and team.person_on_events_mode != PersonsOnEventsMode.DISABLED


class PersonsPropertiesSubQuery(SessionRecordingsListingBaseQuery):
    def __init__(self, team: Team, query: RecordingsQuery):
        super().__init__(team, query)

    def get_query(self) -> ast.SelectQuery | ast.SelectSetQuery | None:
        if self.person_properties and not poe_is_active(self._team):
            return parse_select(
                """
                SELECT distinct_id
                FROM person_distinct_ids
                WHERE {where_predicates}
                """,
                {
                    "where_predicates": self._where_predicates,
                },
            )
        else:
            return None

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

    @property
    def _where_predicates(self) -> ast.Expr:
        return (
            property_to_expr(self.person_properties, team=self._team)
            if self.person_properties
            else ast.Constant(value=True)
        )


class CohortPropertyGroupsSubQuery(SessionRecordingsListingBaseQuery):
    raw_cohort_to_distinct_id = """
    SELECT
    distinct_id
FROM raw_person_distinct_ids
WHERE distinct_id in (SELECT distinct_id FROM raw_person_distinct_ids WHERE 1=1 AND {cohort_predicate})
GROUP BY distinct_id
HAVING argMax(is_deleted, version) = 0 AND {cohort_predicate}
    """

    def __init__(self, team: Team, query: RecordingsQuery):
        super().__init__(team, query)

    def get_query(self) -> ast.SelectQuery | ast.SelectSetQuery | None:
        if self.cohort_properties:
            return parse_select(
                self.raw_cohort_to_distinct_id,
                {"cohort_predicate": property_to_expr(self.cohort_properties, team=self._team, scope="replay")},
            )

        return None

    @property
    def cohort_properties(self) -> PropertyGroupFilterValue | None:
        cohort_property_groups = [g for g in (self._query.properties or []) if is_cohort_property(g)]
        return (
            PropertyGroupFilterValue(
                type=FilterLogicalOperator.AND_ if self.property_operand == "AND" else FilterLogicalOperator.OR_,
                values=cohort_property_groups,
            )
            if cohort_property_groups
            else None
        )


class PersonsIdCompareOperation(SessionRecordingsListingBaseQuery):
    def __init__(self, team: Team, query: RecordingsQuery):
        super().__init__(team, query)

    def get_operation(self) -> CompareOperation | None:
        q = self.get_query()
        if not q:
            return None

        if poe_is_active(self._team):
            return ast.CompareOperation(
                # this hits the distributed events table from the distributed session_replay_events table
                # so we should use GlobalIn
                # see https://clickhouse.com/docs/en/sql-reference/operators/in#distributed-subqueries
                op=ast.CompareOperationOp.GlobalIn,
                left=ast.Field(chain=["session_id"]),
                right=q,
            )
        else:
            return ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["distinct_id"]),
                right=q,
            )

    def get_query(self) -> ast.SelectQuery | ast.SelectSetQuery | None:
        if not self._query.person_uuid:
            return None

        # anchor to python now so that tests can freeze time
        now = datetime.utcnow()

        if poe_is_active(self._team):
            return parse_select(
                """
                select
                    distinct `$session_id`
                from
                    events
                where
                    person_id = {person_id}
                    and timestamp <= {now}
                    and timestamp >= {ttl_date}
                    and timestamp >= {date_from}
                    and timestamp <= {date_to}
                    and notEmpty(`$session_id`)
                """,
                {
                    "person_id": ast.Constant(value=self._query.person_uuid),
                    "ttl_days": ast.Constant(value=self.ttl_days),
                    "date_from": ast.Constant(value=self.query_date_range.date_from()),
                    "date_to": ast.Constant(value=self.query_date_range.date_to()),
                    "now": ast.Constant(value=now),
                    "ttl_date": ast.Constant(value=now - timedelta(days=self.ttl_days)),
                },
            )
        else:
            return parse_select(
                """
                SELECT distinct_id
                FROM person_distinct_ids
                WHERE person_id = {person_id}
                """,
                {
                    "person_id": ast.Constant(value=self._query.person_uuid),
                },
            )


def _entity_to_expr(entity: EventsNode | ActionsNode) -> ast.Expr:
    # KLUDGE: we should be able to use NodeKind.ActionsNode here but mypy :shrug:
    if entity.kind == "ActionsNode":
        action = Action.objects.get(pk=entity.id)
        return action_to_expr(action)
    else:
        if entity.event is None:
            return ast.Constant(value=True)

        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["events", "event"]),
            right=ast.Constant(value=entity.name),
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
