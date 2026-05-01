import dataclasses
from typing import Optional, TypeVar, cast

from dateutil.parser import isoparse

from posthog.schema import HogQLFilters, SessionPropertyFilter

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.ai_events import AiEventsTable
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.groups import GroupsTable
from posthog.hogql.database.schema.logs import LogAttributesTable, LogsTable
from posthog.hogql.database.schema.sessions_v1 import SessionsTableV1
from posthog.hogql.database.schema.sessions_v2 import SessionsTableV2
from posthog.hogql.database.schema.sessions_v3 import SessionsTableV3
from posthog.hogql.database.schema.spans import TraceSpansTable
from posthog.hogql.errors import QueryError
from posthog.hogql.property import property_to_expr
from posthog.hogql.visitor import CloningVisitor

from posthog.models import Team
from posthog.utils import relative_date_parse

T = TypeVar("T", bound=ast.Expr)
DEFAULT_TEAM = cast(Team, None)


@dataclasses.dataclass
class CompareOperationWrapper:
    compare_operation: ast.CompareOperation
    skip: bool = False


def replace_filters(node: T, filters: Optional[HogQLFilters], team: Team, database: Optional[Database] = None) -> T:
    if database is None:
        database = Database.create_for(team=team)
    return ReplaceFilters(filters, team, database).visit(node)


class ReplaceFilters(CloningVisitor):
    def __init__(
        self,
        filters: Optional[HogQLFilters],
        team: Team = DEFAULT_TEAM,
        database: Optional[Database] = None,
    ):
        super().__init__()
        self.filters = filters
        self.team = team
        self.database = database
        self.selects: list[ast.SelectQuery] = []
        self.compare_operations: list[CompareOperationWrapper] = []

    def _resolve_table(self, chain: list) -> Optional[Table]:
        """Resolve an AST field chain to the underlying database table, or None if not found."""
        if self.database is None:
            return None
        try:
            return self.database.get_table([str(c) for c in chain])
        except Exception:
            return None

    def visit_select_query(self, node):
        self.selects.append(node)
        node = super().visit_select_query(node)
        self.selects.pop()
        return node

    def visit_compare_operation(self, node):
        self.compare_operations.append(CompareOperationWrapper(compare_operation=node, skip=False))
        node = super().visit_compare_operation(node)
        compare_wrapper = self.compare_operations.pop()
        if compare_wrapper.skip:
            return ast.CompareOperation(
                left=ast.Constant(value=True),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=True),
            )
        return node

    def visit_placeholder(self, node):
        no_filters = self.filters is None or not self.filters.model_fields_set

        if node.chain == ["filters"]:
            last_select = self.selects[-1]
            last_join = last_select.select_from
            found_events = False
            found_sessions = False
            found_logs = False
            found_traces = False
            found_groups = False
            while last_join is not None:
                if isinstance(last_join.table, ast.Field):
                    resolved = self._resolve_table(last_join.table.chain)
                    if isinstance(resolved, (EventsTable, AiEventsTable)):
                        found_events = True
                    if isinstance(resolved, SessionsTableV1 | SessionsTableV2 | SessionsTableV3):
                        found_sessions = True
                    if isinstance(resolved, (LogsTable, LogAttributesTable)):
                        found_logs = True
                    if isinstance(resolved, TraceSpansTable):
                        found_traces = True
                    if isinstance(resolved, GroupsTable):
                        found_groups = True
                    if found_events and found_sessions or found_groups:
                        break
                last_join = last_join.next_join

            if not any([found_events, found_sessions, found_logs, found_traces, found_groups]):
                raise QueryError(
                    f"Cannot use 'filters' placeholder in a SELECT clause that does not select from the events, sessions, logs, traces or groups table."
                )

            if no_filters:
                return ast.Constant(value=True)

            assert self.filters is not None

            exprs: list[ast.Expr] = []
            if self.filters.properties is not None:
                if found_sessions:
                    session_properties = [p for p in self.filters.properties if isinstance(p, SessionPropertyFilter)]
                    non_session_properties = [
                        p for p in self.filters.properties if not isinstance(p, SessionPropertyFilter)
                    ]
                    if non_session_properties and not found_events:
                        raise QueryError(
                            "Can only use session properties in a filter when selecting from only the sessions table."
                        )
                    exprs.append(property_to_expr(session_properties, self.team, scope="session"))
                    exprs.append(property_to_expr(non_session_properties, self.team, scope="event"))
                elif found_groups:
                    exprs.append(property_to_expr(self.filters.properties, self.team, scope="group"))
                else:
                    exprs.append(property_to_expr(self.filters.properties, self.team, scope="event"))

            timestamp_field = ast.Field(chain=["$start_timestamp"])
            if found_events or found_logs or found_traces:
                timestamp_field = ast.Field(chain=["timestamp"])
            if found_groups:
                timestamp_field = ast.Field(chain=["created_at"])

            dateTo = self.filters.dateRange.date_to if self.filters.dateRange else None
            if dateTo is not None:
                try:
                    parsed_date = isoparse(dateTo)
                    if parsed_date.tzinfo is None:
                        parsed_date = parsed_date.replace(tzinfo=self.team.timezone_info)
                except ValueError:
                    parsed_date = relative_date_parse(dateTo, self.team.timezone_info)
                exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Lt,
                        left=timestamp_field,
                        right=ast.Constant(value=parsed_date),
                    )
                )

            # limit to the last 30d by default
            dateFrom = self.filters.dateRange.date_from if self.filters.dateRange else None
            if dateFrom is not None and dateFrom != "all":
                try:
                    parsed_date = isoparse(dateFrom)
                    if parsed_date.tzinfo is None:
                        parsed_date = parsed_date.replace(tzinfo=self.team.timezone_info)
                except ValueError:
                    parsed_date = relative_date_parse(dateFrom, self.team.timezone_info)
                exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=timestamp_field,
                        right=ast.Constant(value=parsed_date),
                    )
                )

            if self.filters.filterTestAccounts:
                for prop in self.team.test_account_filters or []:
                    exprs.append(property_to_expr(prop, self.team))

            if len(exprs) == 0:
                return ast.Constant(value=True)
            if len(exprs) == 1:
                return exprs[0]
            return ast.And(exprs=exprs)
        if node.chain == ["filters", "dateRange", "from"]:
            compare_op_wrapper = self.compare_operations[-1]

            if no_filters:
                compare_op_wrapper.skip = True
                return ast.Constant(value=True)

            assert self.filters is not None

            dateFrom = self.filters.dateRange.date_from if self.filters.dateRange else None
            if dateFrom is not None and dateFrom != "all":
                try:
                    parsed_date = isoparse(dateFrom)
                    if parsed_date.tzinfo is None:
                        parsed_date = parsed_date.replace(tzinfo=self.team.timezone_info)
                except ValueError:
                    parsed_date = relative_date_parse(dateFrom, self.team.timezone_info)

                return ast.Constant(value=parsed_date)
            else:
                compare_op_wrapper.skip = True
                return ast.Constant(value=True)
        if node.chain == ["filters", "dateRange", "to"]:
            compare_op_wrapper = self.compare_operations[-1]

            if no_filters:
                compare_op_wrapper.skip = True
                return ast.Constant(value=True)

            assert self.filters is not None

            dateTo = self.filters.dateRange.date_to if self.filters.dateRange else None
            if dateTo is not None:
                try:
                    parsed_date = isoparse(dateTo)
                    if parsed_date.tzinfo is None:
                        parsed_date = parsed_date.replace(tzinfo=self.team.timezone_info)
                except ValueError:
                    parsed_date = relative_date_parse(dateTo, self.team.timezone_info)
                return ast.Constant(value=parsed_date)
            else:
                compare_op_wrapper.skip = True
                return ast.Constant(value=True)

        if node.chain and node.chain[0] == "filters":
            chain_str = ".".join(str(c) for c in node.chain)
            raise QueryError(
                f"Unsupported filters placeholder `{{{chain_str}}}`. "
                "Supported filters placeholders are: `{filters}`, `{filters.dateRange.from}`, `{filters.dateRange.to}`."
            )

        return super().visit_placeholder(node)
