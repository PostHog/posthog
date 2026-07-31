import re
import dataclasses
from datetime import datetime
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
from posthog.utils import relative_date_parse_with_delta_mapping

T = TypeVar("T", bound=ast.Expr)
DEFAULT_TEAM = cast(Team, None)

DATE_ONLY_REGEX = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")
# Relative units below one day ("-1h", "-30M") describe rolling windows (e.g. the logs and traces
# live views) where snapping to calendar boundaries would change the window's meaning.
SUB_DAY_DELTA_KEYS = frozenset(["hours", "minutes", "seconds"])


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
        self._now: Optional[datetime] = None

    def _current_time(self) -> datetime:
        # One shared "now" so both bounds of the range resolve against the same instant
        if self._now is None:
            self._now = datetime.now(tz=self.team.timezone_info)
        return self._now

    def _parse_date_from(self) -> tuple[Optional[datetime], Optional[dict[str, int]]]:
        date_from = self.filters.dateRange.date_from if self.filters and self.filters.dateRange else None
        if date_from is None or date_from == "all":
            return None, None
        parsed_date, delta_mapping, _position = relative_date_parse_with_delta_mapping(
            date_from,
            self.team.timezone_info,
            now=self._current_time(),
            team_week_start_day=self.team.week_start_day,
        )
        return parsed_date, delta_mapping

    def _resolve_date_from(self) -> Optional[datetime]:
        """Lower bound of the date range, resolved the way QueryDateRange resolves it for insights:
        relative values in day-or-coarser units ("mStart", "-7d") snap to the start of the day instead
        of keeping the current time of day. Sub-day units ("-1h") stay exact rolling windows, explicit
        datetimes are used verbatim, and "all" means no lower bound."""
        parsed_date, delta_mapping = self._parse_date_from()
        if parsed_date is None:
            return None
        if delta_mapping is None or SUB_DAY_DELTA_KEYS & delta_mapping.keys():
            return parsed_date
        return parsed_date.replace(hour=0, minute=0, second=0, microsecond=0)

    def _open_ended_date_to(self) -> Optional[datetime]:
        """A missing date_to means "up to now" when a date filter is in use — matching how insights
        resolve the same range instead of leaving the query unbounded (which would include
        future-dated rows). With no date filter at all, with date_from="all" (which promises the
        whole table, including future-dated warehouse rows), or with a sub-day rolling date_from
        ("-1h"), the range stays open-ended."""
        date_range = self.filters.dateRange if self.filters else None
        if date_range is None or date_range.date_from is None or date_range.date_from == "all":
            return None
        _parsed_date, delta_mapping = self._parse_date_from()
        if delta_mapping is not None and SUB_DAY_DELTA_KEYS & delta_mapping.keys():
            return None
        return self._current_time()

    def _resolve_date_to(self) -> tuple[Optional[datetime], bool]:
        """Upper bound of the date range, resolved the way QueryDateRange resolves it for
        day-interval insights: relative and date-only values snap to the end of the day, and a
        missing date_to resolves to the end of today, so ranges like "This month" include all of
        today but nothing from the future. Explicit datetimes are used verbatim, relative sub-day
        values ("-1h") stay exact, and explicitDate disables the end-of-day snapping.

        Also returns whether the bound was snapped to an end-of-day instant. Snapped bounds land
        on 23:59:59.999999 and must be compared inclusively to cover the whole day; exact bounds
        keep the strict comparison so half-open windows (like the logs count-ranges bucket ends,
        documented as exclusive) don't gain their boundary row."""
        date_range = self.filters.dateRange if self.filters else None
        date_to = date_range.date_to if date_range else None
        explicit_date = bool(date_range.explicitDate) if date_range else False

        parsed_date: Optional[datetime]
        if date_to is None:
            parsed_date = self._open_ended_date_to()
        else:
            if not DATE_ONLY_REGEX.match(date_to):
                try:
                    verbatim_date = isoparse(date_to)
                    if verbatim_date.tzinfo is None:
                        verbatim_date = verbatim_date.replace(tzinfo=self.team.timezone_info)
                    return verbatim_date, False
                except ValueError:
                    pass
            parsed_date, delta_mapping, _position = relative_date_parse_with_delta_mapping(
                date_to,
                self.team.timezone_info,
                now=self._current_time(),
                team_week_start_day=self.team.week_start_day,
            )
            if delta_mapping is not None and SUB_DAY_DELTA_KEYS & delta_mapping.keys():
                return parsed_date, False
        if parsed_date is None:
            return None, False
        if explicit_date:
            return parsed_date, False
        return parsed_date.replace(hour=23, minute=59, second=59, microsecond=999999), True

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

            date_to, date_to_inclusive = self._resolve_date_to()
            if date_to is not None:
                exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.LtEq if date_to_inclusive else ast.CompareOperationOp.Lt,
                        left=timestamp_field,
                        right=ast.Constant(value=date_to),
                    )
                )

            date_from = self._resolve_date_from()
            if date_from is not None:
                exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=timestamp_field,
                        right=ast.Constant(value=date_from),
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

            date_from = self._resolve_date_from()
            if date_from is not None:
                return ast.Constant(value=date_from)
            else:
                compare_op_wrapper.skip = True
                return ast.Constant(value=True)
        if node.chain == ["filters", "dateRange", "to"]:
            compare_op_wrapper = self.compare_operations[-1]

            if no_filters:
                compare_op_wrapper.skip = True
                return ast.Constant(value=True)

            assert self.filters is not None

            date_to, _date_to_inclusive = self._resolve_date_to()
            if date_to is not None:
                return ast.Constant(value=date_to)
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
