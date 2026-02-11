import re
from datetime import timedelta
from typing import Optional

from django.utils.timezone import now

from posthog.schema import CachedSessionsQueryResponse, DashboardFilter, SessionsQuery, SessionsQueryResponse

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_order_expr
from posthog.hogql.property import action_to_expr, has_aggregation, map_virtual_properties, property_to_expr

from posthog.api.person import PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
from posthog.api.utils import get_pk_or_uuid
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models import Action, Person
from posthog.models.person.person import READ_DB_FOR_PERSONS, get_distinct_ids_for_subquery
from posthog.utils import relative_date_parse

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
        # Build coalesce expression for person properties
        props = []
        for key in property_keys:
            if re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", key):
                props.append(f"toString(__person_lookup.properties.{key})")
            else:
                props.append(f"toString(__person_lookup.properties.`{key}`)")

        # Create a tuple with (display_name, person_id, distinct_id)
        # Use sessions.distinct_id to avoid ambiguity with pdi.distinct_id
        coalesce_expr = f"coalesce({', '.join([*props, 'sessions.distinct_id'])})"
        return f"({coalesce_expr}, toString(__person_lookup.id), sessions.distinct_id)"

    def select_cols(self) -> tuple[list[str], list[ast.Expr]]:
        needs_person_join = self._needs_person_join()
        select_input: list[str] = []
        for col in self.select_input_raw():
            col_name = col.split("--")[0].strip()
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

    def _needs_person_join(self) -> bool:
        """Check if any selected column, orderBy, or filter requires person join."""
        for col in self.select_input_raw():
            col_name = col.split("--")[0].strip()
            if col_name == "person_display_name" or col_name.startswith("person.properties."):
                return True
        if self.query.orderBy:
            for col in self.query.orderBy:
                col_name = col.split("--")[0].strip()
                if col_name == "person_display_name" or col_name.startswith("person.properties."):
                    return True
        if self.query.properties:
            for prop in self.query.properties:
                if hasattr(prop, "type") and prop.type == "person":
                    return True
        return False

    def _transform_person_property_col(self, col: str) -> str:
        """Transform person.properties.X to use __person_lookup alias."""
        if "--" in col:
            expr, comment = col.split("--", 1)
            expr = expr.strip()
            comment = comment.strip()
        else:
            expr = col.strip()
            comment = None

        transformed = expr.replace("person.properties.", "__person_lookup.properties.")

        if comment:
            return f"{transformed} -- {comment}"
        return transformed

    def _transform_session_property_col(self, col: str, needs_person_join: bool) -> str:
        """Transform session.X to X or sessions.X (when person join is present to avoid ambiguity)."""
        if "--" in col:
            expr, comment = col.split("--", 1)
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
            return f"{transformed} -- {comment}"
        return transformed

    def _person_property_to_expr(self, prop) -> ast.Expr:
        """Convert a person property filter to an expression using __person_lookup."""
        key = prop.key
        value = prop.value
        operator = getattr(prop, "operator", "exact")

        # Build the property field reference
        if re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", key):
            field = ast.Field(chain=["__person_lookup", "properties", key])
        else:
            field = ast.Field(chain=["__person_lookup", "properties", key])

        # Handle different operators
        if operator == "exact":
            if isinstance(value, list):
                return ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=field,
                    right=ast.Tuple(exprs=[ast.Constant(value=v) for v in value]),
                )
            return ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=field,
                right=ast.Constant(value=value),
            )
        elif operator == "is_not":
            if isinstance(value, list):
                return ast.CompareOperation(
                    op=ast.CompareOperationOp.NotIn,
                    left=field,
                    right=ast.Tuple(exprs=[ast.Constant(value=v) for v in value]),
                )
            return ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=field,
                right=ast.Constant(value=value),
            )
        elif operator == "icontains":
            return ast.CompareOperation(
                op=ast.CompareOperationOp.ILike,
                left=field,
                right=ast.Constant(value=f"%{value}%"),
            )
        elif operator == "not_icontains":
            return ast.CompareOperation(
                op=ast.CompareOperationOp.NotILike,
                left=field,
                right=ast.Constant(value=f"%{value}%"),
            )
        elif operator == "regex":
            return ast.Call(name="match", args=[field, ast.Constant(value=value)])
        elif operator == "not_regex":
            return ast.Not(expr=ast.Call(name="match", args=[field, ast.Constant(value=value)]))
        elif operator == "is_set":
            return ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=field,
                right=ast.Constant(value=None),
            )
        elif operator == "is_not_set":
            return ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=field,
                right=ast.Constant(value=None),
            )
        elif operator == "gt":
            return ast.CompareOperation(
                op=ast.CompareOperationOp.Gt,
                left=field,
                right=ast.Constant(value=value),
            )
        elif operator == "lt":
            return ast.CompareOperation(
                op=ast.CompareOperationOp.Lt,
                left=field,
                right=ast.Constant(value=value),
            )
        elif operator == "gte":
            return ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=field,
                right=ast.Constant(value=value),
            )
        elif operator == "lte":
            return ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=field,
                right=ast.Constant(value=value),
            )
        else:
            # Fallback to exact match for unknown operators
            return ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=field,
                right=ast.Constant(value=value),
            )

    def to_query(self) -> ast.SelectQuery:
        with self.timings.measure("build_ast"):
            # columns & group_by
            with self.timings.measure("columns"):
                select_input, select = self.select_cols()

            with self.timings.measure("aggregations"):
                group_by: list[ast.Expr] = [column for column in select if not has_aggregation(column)]
                aggregations: list[ast.Expr] = [column for column in select if has_aggregation(column)]
                has_any_aggregation = len(aggregations) > 0

            # filters
            with self.timings.measure("filters"):
                with self.timings.measure("where"):
                    where_input = self.query.where or []
                    where_exprs = [parse_expr(expr, timings=self.timings) for expr in where_input]
                if self.query.properties:
                    with self.timings.measure("properties"):
                        # Separate person properties from session properties
                        # Cohort properties are still filtered out as they require more complex handling
                        session_properties = []
                        person_properties = []
                        for prop in self.query.properties:
                            if hasattr(prop, "type"):
                                if prop.type in ("cohort", "static-cohort", "precalculated-cohort"):
                                    continue  # Skip cohort properties
                                elif prop.type == "person":
                                    person_properties.append(prop)
                                    continue
                            session_properties.append(prop)

                        where_exprs.extend(
                            property_to_expr(property, self.team, scope="session") for property in session_properties
                        )

                        # Handle person properties using the __person_lookup join
                        for prop in person_properties:
                            where_exprs.append(self._person_property_to_expr(prop))
                if self.query.fixedProperties:
                    with self.timings.measure("fixed_properties"):
                        where_exprs.extend(
                            property_to_expr(property, self.team, scope="session")
                            for property in self.query.fixedProperties
                        )
                if self.query.personId:
                    with self.timings.measure("person_id"):
                        person: Optional[Person] = get_pk_or_uuid(
                            Person.objects.db_manager(READ_DB_FOR_PERSONS).filter(team=self.team), self.query.personId
                        ).first()
                        where_exprs.append(
                            ast.CompareOperation(
                                left=ast.Call(name="cityHash64", args=[ast.Field(chain=["distinct_id"])]),
                                right=ast.Tuple(
                                    exprs=[
                                        ast.Call(name="cityHash64", args=[ast.Constant(value=id)])
                                        for id in get_distinct_ids_for_subquery(person, self.team)
                                    ]
                                ),
                                op=ast.CompareOperationOp.In,
                            )
                        )
                if self.query.filterTestAccounts:
                    with self.timings.measure("test_account_filters"):
                        for prop in self.team.test_account_filters or []:
                            where_exprs.append(property_to_expr(prop, self.team))

                # Filter sessions by events
                if self.query.event or self.query.actionId:
                    with self.timings.measure("event_filter"):
                        # Build the events subquery conditions
                        event_where_exprs = []

                        if self.query.event:
                            event_where_exprs.append(
                                parse_expr(
                                    "event = {event}",
                                    {"event": ast.Constant(value=self.query.event)},
                                    timings=self.timings,
                                )
                            )
                        elif self.query.actionId:
                            try:
                                action = Action.objects.get(
                                    pk=self.query.actionId, team__project_id=self.team.project_id
                                )
                            except Action.DoesNotExist:
                                raise Exception("Action does not exist")
                            if not action.steps:
                                raise Exception("Action does not have any match groups")
                            event_where_exprs.append(action_to_expr(action))

                        # Add event property filters if specified
                        if self.query.eventProperties:
                            event_where_exprs.extend(
                                property_to_expr(property, self.team) for property in self.query.eventProperties
                            )

                        # Add timestamp filter to events subquery based on session date range
                        if self.query.after and self.query.after != "all":
                            parsed_after = relative_date_parse(self.query.after, self.team.timezone_info)
                            event_where_exprs.append(
                                parse_expr(
                                    "timestamp > {timestamp}",
                                    {"timestamp": ast.Constant(value=parsed_after)},
                                    timings=self.timings,
                                )
                            )
                        before = self.query.before or (now() + timedelta(seconds=5)).isoformat()
                        parsed_before = relative_date_parse(before, self.team.timezone_info)
                        event_where_exprs.append(
                            parse_expr(
                                "timestamp < {timestamp}",
                                {"timestamp": ast.Constant(value=parsed_before)},
                                timings=self.timings,
                            )
                        )

                        # Build subquery: session_id IN (SELECT DISTINCT $session_id FROM events WHERE ...)
                        events_subquery = ast.SelectQuery(
                            select=[ast.Field(chain=["$session_id"])],
                            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                            where=ast.And(exprs=event_where_exprs) if len(event_where_exprs) > 0 else None,
                            distinct=True,
                        )

                        where_exprs.append(
                            ast.CompareOperation(
                                left=ast.Field(chain=["session_id"]),
                                right=events_subquery,
                                op=ast.CompareOperationOp.In,
                            )
                        )

            with self.timings.measure("timestamps"):
                # prevent accidentally future sessions from being visible by default
                before = self.query.before or (now() + timedelta(seconds=5)).isoformat()
                parsed_date = relative_date_parse(before, self.team.timezone_info)
                where_exprs.append(
                    parse_expr(
                        "$start_timestamp < {timestamp}",
                        {"timestamp": ast.Constant(value=parsed_date)},
                        timings=self.timings,
                    )
                )

                # limit to the last 24h by default
                after = self.query.after or "-24h"
                if after != "all":
                    parsed_date = relative_date_parse(after, self.team.timezone_info)
                    where_exprs.append(
                        parse_expr(
                            "$start_timestamp > {timestamp}",
                            {"timestamp": ast.Constant(value=parsed_date)},
                            timings=self.timings,
                        )
                    )

            # where & having
            with self.timings.measure("where"):
                where_list = [expr for expr in where_exprs if not has_aggregation(expr)]
                where: ast.Expr | None = ast.And(exprs=where_list) if len(where_list) > 0 else None
                having_list = [expr for expr in where_exprs if has_aggregation(expr)]
                having: ast.Expr | None = ast.And(exprs=having_list) if len(having_list) > 0 else None

            # order by
            with self.timings.measure("order"):
                if self.query.orderBy is not None:
                    order_columns: list[str] = []
                    for col in self.query.orderBy:
                        col_name = col.split("--")[0].strip()
                        if col_name == "person_display_name":
                            # Replace person_display_name with the actual expression
                            property_keys = (
                                self.team.person_display_name_properties or PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
                            )
                            props = []
                            for key in property_keys:
                                if re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*$", key):
                                    props.append(f"toString(__person_lookup.properties.{key})")
                                else:
                                    props.append(f"toString(__person_lookup.properties.`{key}`)")
                            expr = f"(coalesce({', '.join([*props, 'sessions.distinct_id'])}), toString(__person_lookup.id))"
                            new_col = re.sub(r"person_display_name -- Person\s*", expr, col)
                            order_columns.append(new_col)
                        elif col_name.startswith("person.properties."):
                            order_columns.append(self._transform_person_property_col(col))
                        elif col_name.startswith("session."):
                            order_columns.append(self._transform_session_property_col(col, self._needs_person_join()))
                        else:
                            order_columns.append(col)
                    order_by = [parse_order_expr(column, timings=self.timings) for column in order_columns]
                elif "count()" in select_input:
                    order_by = [ast.OrderExpr(expr=parse_expr("count()"), order="DESC")]
                elif len(aggregations) > 0:
                    order_by = [ast.OrderExpr(expr=aggregations[0], order="DESC")]
                elif "$start_timestamp" in select_input:
                    order_by = [ast.OrderExpr(expr=ast.Field(chain=["$start_timestamp"]), order="DESC")]
                elif len(select) > 0:
                    order_by = [ast.OrderExpr(expr=select[0], order="ASC")]
                else:
                    order_by = []

            with self.timings.measure("select"):
                # Build the FROM clause, optionally adding person join
                select_from = ast.JoinExpr(table=ast.Field(chain=["sessions"]))

                if self._needs_person_join():
                    # Join sessions -> person_distinct_ids -> persons
                    # First join: sessions.distinct_id -> person_distinct_ids.distinct_id
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
                    # Second join: person_distinct_ids.person_id -> persons.id
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

                stmt = ast.SelectQuery(
                    select=select,
                    select_from=select_from,
                    where=where,
                    having=having,
                    group_by=group_by if has_any_aggregation else None,
                    order_by=order_by,
                )

                return stmt

    def _calculate(self) -> SessionsQueryResponse:
        query_result = self.paginator.execute_hogql_query(
            query=self.to_query(),
            team=self.team,
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
            if col.split("--")[0].strip() == "person_display_name":
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
