import re
from datetime import timedelta
from typing import Optional

from django.utils.timezone import now

from posthog.schema import (
    CachedSessionsQueryResponse,
    DashboardFilter,
    EventPropertyFilter,
    PropertyOperator,
    SessionsQuery,
    SessionsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_order_expr
from posthog.hogql.property import action_to_expr, has_aggregation, map_virtual_properties, property_to_expr

from posthog.api.person import PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
from posthog.clickhouse.query_tagging import tag_contains_user_hogql
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.person_display_name import person_display_name_property_exprs
from posthog.models import Person
from posthog.models.person.person import MAX_LIMIT_DISTINCT_IDS, get_distinct_ids_for_subquery
from posthog.models.person.util import get_person_by_pk_or_uuid
from posthog.models.property import Property
from posthog.models.property.property import STRING_PREFIX_SUFFIX_OPERATORS
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.utils import relative_date_parse

from products.actions.backend.models.action import Action

COLUMN_COMMENT_SEPARATOR = " -- "
SUPPORTED_PERSON_PROPERTY_OPERATORS = frozenset(
    {
        "exact",
        "is_not",
        "icontains",
        "not_icontains",
        "regex",
        "not_regex",
        "is_set",
        "is_not_set",
        "gt",
        "lt",
        "gte",
        "lte",
    }
    | set(STRING_PREFIX_SUFFIX_OPERATORS)
)
PERSON_LIKE_OPERATORS = frozenset({"icontains", "not_icontains"} | set(STRING_PREFIX_SUFFIX_OPERATORS))


def _extract_session_id_values(prop) -> Optional[list[str]]:
    # Returns a list of session IDs extracted from a `$session_id` exact-match
    # EventPropertyFilter, or None if the prop is not such a filter and should
    # continue to flow through the events subquery. An empty list is returned
    # verbatim so callers can emit a zero-result constraint — matching the
    # semantic intent of `$session_id IN ()`.
    if not isinstance(prop, EventPropertyFilter):
        return None
    if prop.key != "$session_id":
        return None
    if prop.operator not in (None, PropertyOperator.EXACT):
        return None
    if prop.value is None:
        return None
    if isinstance(prop.value, list):
        return [str(v) for v in prop.value]
    return [str(prop.value)]


# Allow-listed fields returned when you select "*" from sessions
SELECT_STAR_FROM_SESSIONS_FIELDS = [
    "session_id",
    "distinct_id",
    "$start_timestamp",
    "$end_timestamp",
    "$session_duration",
    "$entry_current_url",
    "$end_current_url",
    "$pageview_count",
    "$autocapture_count",
    "$screen_count",
    "$is_bounce",
]


class SessionsQueryRunner(AnalyticsQueryRunner[SessionsQueryResponse]):
    query: SessionsQuery
    cached_response: CachedSessionsQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context, limit=self.query.limit, offset=self.query.offset
        )

    def _build_person_display_name_expr(self) -> str:
        """Build the HogQL expression for person_display_name using a subquery join."""
        property_keys = self.team.person_display_name_properties or PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
        props = person_display_name_property_exprs(property_keys, "__person_lookup.properties")
        # Create a tuple with (display_name, person_id, distinct_id)
        # Use sessions.distinct_id to avoid ambiguity with pdi.distinct_id
        coalesce_expr = f"coalesce({', '.join([*props, 'sessions.distinct_id'])})"
        return f"({coalesce_expr}, toString(__person_lookup.id), sessions.distinct_id)"

    def select_cols(self) -> tuple[list[str], list[ast.Expr]]:
        needs_person_join = self._needs_person_join()
        select_input: list[str] = []
        for col in self.select_input_raw():
            col_name = col.split(COLUMN_COMMENT_SEPARATOR)[0].strip()
            # Selecting a "*" expands the list of columns
            if col == "*":
                # Qualify with sessions. prefix when person join is present to avoid ambiguity
                # (e.g. distinct_id exists on both sessions and person_distinct_ids)
                fields = (
                    [f"sessions.{f}" for f in SELECT_STAR_FROM_SESSIONS_FIELDS]
                    if needs_person_join
                    else SELECT_STAR_FROM_SESSIONS_FIELDS
                )
                select_input.append(f"tuple({', '.join(fields)})")
            elif col_name == "person_display_name":
                select_input.append(self._build_person_display_name_expr())
            elif col_name.startswith("person.properties."):
                select_input.append(self._transform_person_property_col(col))
            elif col_name.startswith("session."):
                # Transform session.X to just X (or sessions.X when person join is present)
                select_input.append(self._transform_session_property_col(col, needs_person_join))
            else:
                select_input.append(col)
        return select_input, [
            map_virtual_properties(parse_expr(column, timings=self.timings)) for column in select_input
        ]

    @staticmethod
    def _prop_type(prop) -> Optional[str]:
        """Read a filter's `type`, whether it is a dict or a pydantic model."""
        if isinstance(prop, dict):
            return prop.get("type")
        return getattr(prop, "type", None)

    @staticmethod
    def _col_refs_person(col: str) -> bool:
        col_name = col.split(COLUMN_COMMENT_SEPARATOR)[0].strip()
        return col_name == "person_display_name" or col_name.startswith("person.properties.")

    def _needs_person_join(self) -> bool:
        """Check if any selected column, orderBy, or filter requires person join."""
        if any(self._col_refs_person(col) for col in self.select_input_raw()):
            return True
        if any(self._col_refs_person(col) for col in self.query.orderBy or []):
            return True
        if any(self._prop_type(prop) == "person" for prop in self.query.properties or []):
            return True
        if self.query.filterTestAccounts:
            return any(self._prop_type(prop) == "person" for prop in self._get_test_account_filters())
        return False

    def _get_test_account_filters(self) -> list:
        return self.team.test_account_filters or []

    def _transform_person_property_col(self, col: str) -> str:
        """Transform person.properties.X to use __person_lookup alias."""
        if COLUMN_COMMENT_SEPARATOR in col:
            expr, comment = col.split(COLUMN_COMMENT_SEPARATOR, 1)
            expr = expr.strip()
            comment = comment.strip()
        else:
            expr = col.strip()
            comment = None

        transformed = expr.replace("person.properties.", "__person_lookup.properties.")

        if comment:
            return f"{transformed}{COLUMN_COMMENT_SEPARATOR}{comment}"
        return transformed

    def _transform_session_property_col(self, col: str, needs_person_join: bool) -> str:
        """Transform session.X to X or sessions.X (when person join is present to avoid ambiguity)."""
        if COLUMN_COMMENT_SEPARATOR in col:
            expr, comment = col.split(COLUMN_COMMENT_SEPARATOR, 1)
            expr = expr.strip()
            comment = comment.strip()
        else:
            expr = col.strip()
            comment = None

        # Remove the "session." prefix and optionally add "sessions." prefix
        property_name = expr[8:]  # Remove "session." prefix
        if needs_person_join:
            transformed = f"sessions.{property_name}"
        else:
            transformed = property_name

        if comment:
            return f"{transformed}{COLUMN_COMMENT_SEPARATOR}{comment}"
        return transformed

    def _person_property_to_expr(self, prop) -> ast.Expr:
        """Convert a person property filter to an expression using __person_lookup."""
        value = prop.value
        operator = getattr(prop, "operator", "exact")

        if operator not in SUPPORTED_PERSON_PROPERTY_OPERATORS:
            raise ValueError(
                f"Unsupported operator '{operator}' for person property filter in sessions query. "
                f"Supported operators: {', '.join(sorted(SUPPORTED_PERSON_PROPERTY_OPERATORS))}"
            )

        # ast.Field handles identifier escaping automatically
        field = ast.Field(chain=["__person_lookup", "properties", prop.key])

        if operator in ("exact", "is_not"):
            return self._person_equality_expr(field, value, negated=operator == "is_not")
        if operator in PERSON_LIKE_OPERATORS:
            return self._person_like_expr(field, value, operator)
        if operator == "regex":
            return ast.Call(name="match", args=[field, ast.Constant(value=value)])
        if operator == "not_regex":
            return ast.Not(expr=ast.Call(name="match", args=[field, ast.Constant(value=value)]))
        if operator == "is_set":
            return ast.CompareOperation(op=ast.CompareOperationOp.NotEq, left=field, right=ast.Constant(value=None))
        if operator == "is_not_set":
            return ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=field, right=ast.Constant(value=None))
        return self._person_numeric_expr(field, value, operator)

    @staticmethod
    def _person_equality_expr(field: ast.Field, value, negated: bool) -> ast.Expr:
        if isinstance(value, list):
            op = ast.CompareOperationOp.NotIn if negated else ast.CompareOperationOp.In
            right: ast.Expr = ast.Tuple(exprs=[ast.Constant(value=v) for v in value])
        else:
            op = ast.CompareOperationOp.NotEq if negated else ast.CompareOperationOp.Eq
            right = ast.Constant(value=value)
        return ast.CompareOperation(op=op, left=field, right=right)

    @staticmethod
    def _person_like_expr(field: ast.Field, value, operator: str) -> ast.Expr:
        if operator in ("icontains", "not_icontains"):
            pattern = f"%{value}%"
        elif operator in ("starts_with", "not_starts_with"):
            pattern = f"{value}%"
        else:  # ends_with, not_ends_with
            pattern = f"%{value}"
        negated = operator in ("not_icontains", "not_starts_with", "not_ends_with")
        op = ast.CompareOperationOp.NotILike if negated else ast.CompareOperationOp.ILike
        return ast.CompareOperation(op=op, left=field, right=ast.Constant(value=pattern))

    @staticmethod
    def _person_numeric_expr(field: ast.Field, value, operator: str) -> ast.Expr:
        op_map = {
            "gt": ast.CompareOperationOp.Gt,
            "lt": ast.CompareOperationOp.Lt,
            "gte": ast.CompareOperationOp.GtEq,
            "lte": ast.CompareOperationOp.LtEq,
        }
        return ast.CompareOperation(
            op=op_map[operator],
            left=ast.Call(name="toFloat", args=[field]),
            right=ast.Constant(value=value),
        )

    def to_query(self) -> ast.SelectQuery:
        with self.timings.measure("build_ast"):
            with self.timings.measure("columns"):
                select_input, select = self.select_cols()

            with self.timings.measure("aggregations"):
                group_by: list[ast.Expr] = [column for column in select if not has_aggregation(column)]
                aggregations: list[ast.Expr] = [column for column in select if has_aggregation(column)]
                has_any_aggregation = len(aggregations) > 0

            with self.timings.measure("filters"):
                where_exprs = self._filter_where_exprs()

            with self.timings.measure("timestamps"):
                where_exprs.extend(self._timestamp_where_exprs())

            with self.timings.measure("where"):
                where_list = [expr for expr in where_exprs if not has_aggregation(expr)]
                where: ast.Expr | None = ast.And(exprs=where_list) if len(where_list) > 0 else None
                having_list = [expr for expr in where_exprs if has_aggregation(expr)]
                having: ast.Expr | None = ast.And(exprs=having_list) if len(having_list) > 0 else None

            with self.timings.measure("order"):
                order_by = self._build_order_by(select_input, select, aggregations)

            with self.timings.measure("select"):
                return ast.SelectQuery(
                    select=select,
                    select_from=self._build_select_from(),
                    where=where,
                    having=having,
                    group_by=group_by if has_any_aggregation else None,
                    order_by=order_by,
                )

    def _filter_where_exprs(self) -> list[ast.Expr]:
        with self.timings.measure("where"):
            where_exprs: list[ast.Expr] = [parse_expr(expr, timings=self.timings) for expr in self.query.where or []]

        if self.query.properties:
            with self.timings.measure("properties"):
                where_exprs.extend(self._property_where_exprs(self.query.properties))
        if self.query.fixedProperties:
            with self.timings.measure("fixed_properties"):
                where_exprs.extend(
                    property_to_expr(property, self.team, scope="session") for property in self.query.fixedProperties
                )
        if self.query.personId:
            with self.timings.measure("person_id"), personhog_caller_tag("persons/sessions-query"):
                where_exprs.append(self._person_id_where_expr(self.query.personId))

        test_account_event_filters: list = []
        if self.query.filterTestAccounts:
            with self.timings.measure("test_account_filters"):
                account_exprs, test_account_event_filters = self._test_account_where_exprs()
                where_exprs.extend(account_exprs)

        if self.query.event or self.query.actionId or self.query.eventProperties or test_account_event_filters:
            with self.timings.measure("event_filter"):
                where_exprs.extend(self._event_filter_where_exprs(test_account_event_filters))
        return where_exprs

    def _property_where_exprs(self, properties: list) -> list[ast.Expr]:
        # Person properties join through __person_lookup; cohort filters need more
        # complex handling and are skipped here.
        session_properties = []
        person_properties = []
        for prop in properties:
            prop_type = self._prop_type(prop)
            if prop_type in ("cohort", "static-cohort", "precalculated-cohort"):
                continue
            if prop_type == "person":
                person_properties.append(prop)
                continue
            session_properties.append(prop)

        exprs = [property_to_expr(property, self.team, scope="session") for property in session_properties]
        exprs.extend(self._person_property_to_expr(prop) for prop in person_properties)
        return exprs

    def _person_id_where_expr(self, person_id: str) -> ast.Expr:
        person: Optional[Person] = get_person_by_pk_or_uuid(
            self.team.pk, person_id, distinct_id_limit=MAX_LIMIT_DISTINCT_IDS
        )
        # Qualify distinct_id with sessions. when person join is present to avoid ambiguity
        distinct_id_chain: list[str | int] = (
            ["sessions", "distinct_id"] if self._needs_person_join() else ["distinct_id"]
        )
        return ast.CompareOperation(
            left=ast.Call(name="cityHash64", args=[ast.Field(chain=distinct_id_chain)]),
            right=ast.Tuple(
                exprs=[
                    ast.Call(name="cityHash64", args=[ast.Constant(value=id)])
                    for id in get_distinct_ids_for_subquery(person, self.team)
                ]
            ),
            op=ast.CompareOperationOp.In,
        )

    def _test_account_where_exprs(self) -> tuple[list[ast.Expr], list]:
        # Session and person filters apply directly; cohort, event, and unknown
        # types route through the events subquery.
        exprs: list[ast.Expr] = []
        event_filters: list = []
        for prop in self._get_test_account_filters():
            prop_type = self._prop_type(prop)
            if prop_type == "session":
                exprs.append(property_to_expr(prop, self.team, scope="session"))
            elif prop_type == "person":
                try:
                    parsed = Property(**prop) if isinstance(prop, dict) else prop
                    exprs.append(self._person_property_to_expr(parsed))
                except (ValueError, TypeError):
                    continue
            else:
                event_filters.append(prop)
        return exprs, event_filters

    def _event_filter_where_exprs(self, test_account_event_filters: list) -> list[ast.Expr]:
        # Extract $session_id exact-match filters and apply them directly on the
        # sessions table, avoiding an unnecessary events table round-trip.
        exprs: list[ast.Expr] = []
        remaining_event_properties = []
        session_id_values: list[str] = []
        extracted_empty_session_id_filter = False
        for prop in self.query.eventProperties or []:
            extracted = _extract_session_id_values(prop)
            if extracted is None:
                remaining_event_properties.append(prop)
            elif not extracted:
                # `$session_id IN ()` must match zero sessions.
                extracted_empty_session_id_filter = True
            else:
                session_id_values.extend(extracted)

        if extracted_empty_session_id_filter:
            exprs.append(ast.Constant(value=False))
        elif session_id_values:
            exprs.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["session_id"]),
                    right=ast.Tuple(exprs=[ast.Constant(value=v) for v in session_id_values]),
                    op=ast.CompareOperationOp.In,
                )
            )

        if self.query.event or self.query.actionId or remaining_event_properties or test_account_event_filters:
            exprs.append(self._events_subquery_where_expr(remaining_event_properties, test_account_event_filters))
        return exprs

    def _events_subquery_where_expr(
        self, remaining_event_properties: list, test_account_event_filters: list
    ) -> ast.Expr:
        event_where_exprs = []
        if self.query.event:
            event_where_exprs.append(
                parse_expr("event = {event}", {"event": ast.Constant(value=self.query.event)}, timings=self.timings)
            )
        elif self.query.actionId:
            try:
                action = Action.objects.get(pk=self.query.actionId, team__project_id=self.team.project_id)
            except Action.DoesNotExist:
                raise Exception("Action does not exist")
            if not action.steps:
                raise Exception("Action does not have any match groups")
            event_where_exprs.append(action_to_expr(action))

        event_where_exprs.extend(property_to_expr(property, self.team) for property in remaining_event_properties)
        event_where_exprs.extend(property_to_expr(prop, self.team) for prop in test_account_event_filters)
        event_where_exprs.extend(self._events_subquery_timestamp_exprs())

        events_subquery = ast.SelectQuery(
            select=[ast.Field(chain=["$session_id"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=event_where_exprs) if len(event_where_exprs) > 0 else None,
            distinct=True,
        )
        return ast.CompareOperation(
            left=ast.Field(chain=["session_id"]),
            right=events_subquery,
            op=ast.CompareOperationOp.In,
        )

    def _events_subquery_timestamp_exprs(self) -> list[ast.Expr]:
        # Match the sessions date range (default -1h when neither bound is set) so we
        # do not scan the full events history when only filterTestAccounts triggers
        # this subquery.
        exprs: list[ast.Expr] = []
        effective_after = self.query.after
        if not effective_after and not self.query.before:
            effective_after = "-1h"
        effective_after = effective_after or "all"
        if effective_after != "all":
            parsed_after = relative_date_parse(effective_after, self.team.timezone_info)
            exprs.append(
                parse_expr(
                    "timestamp > {timestamp}", {"timestamp": ast.Constant(value=parsed_after)}, timings=self.timings
                )
            )
        before = self.query.before or (now() + timedelta(seconds=5)).isoformat()
        parsed_before = relative_date_parse(before, self.team.timezone_info)
        exprs.append(
            parse_expr(
                "timestamp < {timestamp}", {"timestamp": ast.Constant(value=parsed_before)}, timings=self.timings
            )
        )
        return exprs

    def _timestamp_where_exprs(self) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []
        # prevent accidentally future sessions from being visible by default
        before = self.query.before or (now() + timedelta(seconds=5)).isoformat()
        parsed_date = relative_date_parse(before, self.team.timezone_info)
        exprs.append(
            parse_expr(
                "$start_timestamp < {timestamp}", {"timestamp": ast.Constant(value=parsed_date)}, timings=self.timings
            )
        )

        # Default to 1h when no date bounds are provided — unbounded windows on
        # raw_sessions can OOM for high-volume teams. Only apply the default when
        # neither bound is set to avoid creating an empty range when a caller
        # provides only `before`.
        after = self.query.after
        if not after and not self.query.before:
            after = "-1h"
        after = after or "all"
        if after != "all":
            parsed_date = relative_date_parse(after, self.team.timezone_info)
            exprs.append(
                parse_expr(
                    "$start_timestamp > {timestamp}",
                    {"timestamp": ast.Constant(value=parsed_date)},
                    timings=self.timings,
                )
            )
        return exprs

    def _build_order_by(
        self, select_input: list[str], select: list[ast.Expr], aggregations: list[ast.Expr]
    ) -> list[ast.OrderExpr]:
        if self.query.orderBy is not None:
            order_columns = [self._transform_order_column(col) for col in self.query.orderBy]
            return [parse_order_expr(column, timings=self.timings) for column in order_columns]
        if "count()" in select_input:
            return [ast.OrderExpr(expr=parse_expr("count()"), order="DESC")]
        if len(aggregations) > 0:
            return [ast.OrderExpr(expr=aggregations[0], order="DESC")]
        if "$start_timestamp" in select_input:
            return [ast.OrderExpr(expr=ast.Field(chain=["$start_timestamp"]), order="DESC")]
        if len(select) > 0:
            return [ast.OrderExpr(expr=select[0], order="ASC")]
        return []

    def _transform_order_column(self, col: str) -> str:
        col_name = col.split(COLUMN_COMMENT_SEPARATOR)[0].strip()
        if col_name == "person_display_name":
            property_keys = self.team.person_display_name_properties or PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
            props = person_display_name_property_exprs(property_keys, "__person_lookup.properties")
            expr = f"(coalesce({', '.join([*props, 'sessions.distinct_id'])}), toString(__person_lookup.id))"
            return re.sub(r"person_display_name -- Person\s*", expr, col)
        if col_name.startswith("person.properties."):
            return self._transform_person_property_col(col)
        if col_name.startswith("session."):
            return self._transform_session_property_col(col, self._needs_person_join())
        return col

    def _build_select_from(self) -> ast.JoinExpr:
        select_from = ast.JoinExpr(table=ast.Field(chain=["sessions"]))
        if not self._needs_person_join():
            return select_from

        # Join sessions -> person_distinct_ids -> persons
        pdi_join = ast.JoinExpr(
            table=ast.Field(chain=["person_distinct_ids"]),
            join_type="LEFT JOIN",
            alias="__pdi",
            constraint=ast.JoinConstraint(
                expr=ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["sessions", "distinct_id"]),
                    right=ast.Field(chain=["__pdi", "distinct_id"]),
                ),
                constraint_type="ON",
            ),
        )
        persons_join = ast.JoinExpr(
            table=ast.Field(chain=["persons"]),
            join_type="LEFT JOIN",
            alias="__person_lookup",
            constraint=ast.JoinConstraint(
                expr=ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["__pdi", "person_id"]),
                    right=ast.Field(chain=["__person_lookup", "id"]),
                ),
                constraint_type="ON",
            ),
        )
        pdi_join.next_join = persons_join
        select_from.next_join = pdi_join
        return select_from

    def _calculate(self) -> SessionsQueryResponse:
        # `SessionsQuery.select`, `where`, `orderBy` are user-supplied HogQL strings.
        tag_contains_user_hogql()
        query_result = self.paginator.execute_hogql_query(
            query=self.to_query(),
            team=self.team,
            user=self.user,
            query_type="SessionsQuery",
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        # Convert star field from tuple to dict in each result
        if "*" in self.select_input_raw():
            with self.timings.measure("expand_asterisk"):
                star_idx = self.select_input_raw().index("*")
                for index, result in enumerate(self.paginator.results):
                    self.paginator.results[index] = list(result)
                    select = result[star_idx]
                    new_result = dict(zip(SELECT_STAR_FROM_SESSIONS_FIELDS, select))
                    self.paginator.results[index][star_idx] = new_result

        # Convert person_display_name tuple to dict
        for column_index, col in enumerate(self.select_input_raw()):
            if col.split(COLUMN_COMMENT_SEPARATOR)[0].strip() == "person_display_name":
                for index, result in enumerate(self.paginator.results):
                    row = list(self.paginator.results[index])
                    row[column_index] = {
                        "display_name": result[column_index][0],
                        "id": str(result[column_index][1]),
                        "distinct_id": str(result[column_index][2]),
                    }
                    self.paginator.results[index] = row

        return SessionsQueryResponse(
            results=self.paginator.results,
            columns=self.columns(query_result.columns),
            types=[t for _, t in query_result.types] if query_result.types else [],
            timings=self.timings.to_list(),
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter):
        if dashboard_filter.date_to or dashboard_filter.date_from:
            self.query.before = dashboard_filter.date_to
            self.query.after = dashboard_filter.date_from

        if dashboard_filter.properties:
            self.query.properties = (self.query.properties or []) + dashboard_filter.properties

    def columns(self, result_columns: list | None) -> list[str]:
        _, select = self.select_cols()
        columns = result_columns or []
        return [
            columns[idx] if len(columns) > idx and isinstance(select[idx], ast.Alias) else col
            for idx, col in enumerate(self.select_input_raw())
        ]

    def select_input_raw(self) -> list[str]:
        return ["*"] if len(self.query.select) == 0 else self.query.select
