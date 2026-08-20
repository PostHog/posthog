import re
import dataclasses
from datetime import datetime
from typing import Any, Optional, TypeVar, cast

from dateutil.parser import isoparse

from posthog.schema import (
    BreakdownFilter,
    BreakdownType,
    EmptyPropertyFilter,
    HogQLFilters,
    IntervalType,
    MultipleBreakdownType,
    SessionPropertyFilter,
)

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.ai_events import AiEventsTable
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.groups import GroupsTable
from posthog.hogql.database.schema.logs import LogAttributesTable, LogsTable
from posthog.hogql.database.schema.persons import PersonsTable
from posthog.hogql.database.schema.sessions_v1 import SessionsTableV1
from posthog.hogql.database.schema.sessions_v2 import SessionsTableV2
from posthog.hogql.database.schema.sessions_v3 import SessionsTableV3
from posthog.hogql.database.schema.spans import TraceSpansTable
from posthog.hogql.errors import QueryError
from posthog.hogql.property import bound_property_to_expr, property_to_expr
from posthog.hogql.visitor import CloningVisitor, clone_expr

from posthog.models import Property, Team
from posthog.utils import relative_date_parse_with_delta_mapping

T = TypeVar("T", bound=ast.Expr)
DEFAULT_TEAM = cast(Team, None)

DATE_ONLY_REGEX = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")
# Relative units below one day ("-1h", "-30M") describe rolling windows (e.g. the logs and traces
# live views) where snapping to calendar boundaries would change the window's meaning.
SUB_DAY_DELTA_KEYS = frozenset(["hours", "minutes", "seconds"])

# Reserved binding key in {filters(...)} that receives the date range instead of a property filter.
BOUND_TIMESTAMP_KEY = "timestamp"
BOUND_FILTERS_USAGE = (
    "Each argument of {filters(...)} must bind an expression to a filter key with AS, "
    "e.g. {filters(created_at AS timestamp, account_id AS 'account_id')}. "
    "Use null to skip a key, e.g. {filters(null AS timestamp)}."
)
BOUND_BREAKDOWN_USAGE = (
    "Each argument of {filters.breakdown(...)} must bind an expression to a breakdown key with AS, "
    "e.g. {filters.breakdown(properties.plan AS 'plan')}. "
    "Use null to skip a key, e.g. {filters.breakdown(null AS 'plan')}."
)
INTERVAL_UNITS = frozenset(interval.value for interval in IntervalType)


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

    def _date_range_exprs(self, timestamp_expr: ast.Expr) -> list[ast.Expr]:
        """Comparisons pinning `timestamp_expr` inside the resolved date range. The expression is
        cloned per comparison, since bound expressions are caller-supplied AST that must not be
        shared between tree positions."""
        exprs: list[ast.Expr] = []
        date_to, date_to_inclusive = self._resolve_date_to()
        if date_to is not None:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq if date_to_inclusive else ast.CompareOperationOp.Lt,
                    left=clone_expr(timestamp_expr),
                    right=ast.Constant(value=date_to),
                )
            )
        date_from = self._resolve_date_from()
        if date_from is not None:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=clone_expr(timestamp_expr),
                    right=ast.Constant(value=date_from),
                )
            )
        return exprs

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
        # The column-bound form {filters(expr AS key, ...)}: the query author maps each filter key
        # onto an expression of their own query, so the table restrictions of plain {filters} don't
        # apply. A Call never has a chain, so the chain-based branches below can't match it.
        if isinstance(node.expr, ast.Call) and node.expr.name == "filters":
            return self._replace_bound_filters(node.expr)

        # Dotted call forms: {filters.interval('week')} substitutes a granularity constant, and
        # {filters.breakdown(expr AS key, ...)} substitutes the column bound to the selected breakdown.
        if isinstance(node.expr, ast.ExprCall) and isinstance(node.expr.expr, ast.Field):
            call_chain = node.expr.expr.chain
            if call_chain == ["filters", "interval"]:
                return self._replace_interval(node.expr.args)
            if call_chain == ["filters", "breakdown"]:
                return self._replace_breakdown(node.expr.args)
            if call_chain and call_chain[0] == "filters":
                chain_str = ".".join(str(c) for c in call_chain)
                raise QueryError(
                    f"Unsupported filters placeholder `{{{chain_str}(...)}}`. "
                    "Supported call forms are: `{filters(expr AS key, ...)}`, `{filters.interval('day')}`, "
                    "and `{filters.breakdown(expr AS key, ...)}`."
                )

        no_filters = self.filters is None or not self.filters.model_fields_set

        if node.chain == ["filters"]:
            last_select = self.selects[-1]
            last_join = last_select.select_from
            found_events = False
            found_sessions = False
            found_logs = False
            found_traces = False
            found_groups = False
            found_persons = False
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
                    if isinstance(resolved, PersonsTable):
                        found_persons = True
                    if found_events and found_sessions or found_groups:
                        break
                last_join = last_join.next_join

            if not any([found_events, found_sessions, found_logs, found_traces, found_groups, found_persons]):
                raise QueryError(
                    f"Cannot use 'filters' placeholder in a SELECT clause that does not select from the events, sessions, logs, traces, groups or persons table."
                )

            # Person semantics apply only when persons is the sole recognized table; any query that also
            # touches an event-like table keeps its existing scope, so events-joined-to-persons insights
            # are unaffected.
            persons_only = found_persons and not any(
                [found_events, found_sessions, found_logs, found_traces, found_groups]
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
                elif persons_only:
                    exprs.append(property_to_expr(self.filters.properties, self.team, scope="person"))
                else:
                    exprs.append(property_to_expr(self.filters.properties, self.team, scope="event"))

            timestamp_field = ast.Field(chain=["$start_timestamp"])
            if found_events or found_logs or found_traces:
                timestamp_field = ast.Field(chain=["timestamp"])
            if found_groups or persons_only:
                timestamp_field = ast.Field(chain=["created_at"])

            exprs.extend(self._date_range_exprs(timestamp_field))

            if self.filters.filterTestAccounts:
                for prop in self.team.test_account_filters or []:
                    if persons_only:
                        try:
                            exprs.append(property_to_expr(prop, self.team, scope="person"))
                        except (QueryError, NotImplementedError) as error:
                            raise self._persons_test_account_filter_error(prop) from error
                    else:
                        exprs.append(property_to_expr(prop, self.team, scope="event"))

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

        if node.chain == ["filters", "interval"]:
            return self._replace_interval([])

        if node.chain == ["filters", "breakdown"]:
            raise QueryError(
                "{filters.breakdown} needs column bindings. "
                "Write {filters.breakdown(expr AS 'key', ...)} to map breakdown keys onto your columns."
            )

        if node.chain and node.chain[0] == "filters":
            chain_str = ".".join(str(c) for c in node.chain)
            raise QueryError(
                f"Unsupported filters placeholder `{{{chain_str}}}`. "
                "Supported filters placeholders are: `{filters}`, `{filters.dateRange.from}`, `{filters.dateRange.to}`, "
                "`{filters.interval}`, and the column-bound forms `{filters(expr AS key, ...)}` and "
                "`{filters.breakdown(expr AS key, ...)}`."
            )

        return super().visit_placeholder(node)

    def _replace_bound_filters(self, call: ast.Call) -> ast.Expr:
        # Parse bindings before the no-filters early return, so malformed usage surfaces in the
        # SQL editor even while no filter is set yet.
        bindings = self._parse_bindings(call)

        if self.filters is None or not self.filters.model_fields_set:
            return ast.Constant(value=True)

        exprs: list[ast.Expr] = [
            *self._bound_date_range_exprs(bindings),
            *self._bound_property_exprs(bindings),
        ]
        if len(exprs) == 0:
            return ast.Constant(value=True)
        if len(exprs) == 1:
            return exprs[0]
        return ast.And(exprs=exprs)

    def _parse_bindings(self, call: ast.Call) -> dict[str, Optional[ast.Expr]]:
        if call.params is not None or call.distinct:
            raise QueryError(BOUND_FILTERS_USAGE)
        return self._parse_binding_args(call.args, BOUND_FILTERS_USAGE, "{filters(...)}")

    def _parse_binding_args(
        self, args: list[ast.Expr], usage: str, placeholder_label: str
    ) -> dict[str, Optional[ast.Expr]]:
        if not args:
            raise QueryError(usage)
        bindings: dict[str, Optional[ast.Expr]] = {}
        for arg in args:
            if not isinstance(arg, ast.Alias):
                raise QueryError(usage)
            if arg.alias in bindings:
                raise QueryError(f"Filter key '{arg.alias}' is bound more than once in {placeholder_label}.")
            if isinstance(arg.expr, ast.Constant) and arg.expr.value is None:
                # `null AS key` opts the query out of filters on that key.
                bindings[arg.alias] = None
            else:
                bindings[arg.alias] = arg.expr
        return bindings

    def _bound_date_range_exprs(self, bindings: dict[str, Optional[ast.Expr]]) -> list[ast.Expr]:
        date_from = self._resolve_date_from()
        date_to, _date_to_inclusive = self._resolve_date_to()
        if date_from is None and date_to is None:
            return []
        if BOUND_TIMESTAMP_KEY not in bindings:
            # Silently not applying an active date filter would misrepresent the dashboard's state,
            # so the author has to either bind a time column or opt out explicitly.
            raise QueryError(
                "A date filter is set, but {filters(...)} has no timestamp binding. "
                "Bind your time column like {filters(created_at AS timestamp)}, "
                "or write null AS timestamp to exempt this query from date filtering."
            )
        timestamp_expr = bindings[BOUND_TIMESTAMP_KEY]
        if timestamp_expr is None:
            return []
        return self._date_range_exprs(timestamp_expr)

    def _bound_property_exprs(self, bindings: dict[str, Optional[ast.Expr]]) -> list[ast.Expr]:
        assert self.filters is not None
        sources: list[tuple[Any, bool]] = [(prop, False) for prop in self.filters.properties or []]
        if self.filters.filterTestAccounts:
            sources += [(prop, True) for prop in self.team.test_account_filters or []]
        exprs: list[ast.Expr] = []
        for prop, from_test_accounts in sources:
            expr = self._bound_property_expr(prop, bindings, from_test_accounts)
            if expr is not None:
                exprs.append(expr)
        return exprs

    def _bound_property_expr(
        self, prop: Any, bindings: dict[str, Optional[ast.Expr]], from_test_accounts: bool
    ) -> Optional[ast.Expr]:
        if isinstance(prop, EmptyPropertyFilter):
            return None
        try:
            if isinstance(prop, Property):
                property = prop
            elif isinstance(prop, dict):
                property = Property(**prop)
            else:
                property = Property(**prop.dict())
        except (ValueError, TypeError):
            # Incomplete saved filters apply nowhere, matching property_to_expr's behavior.
            return None

        if property.type == "flag":
            # Flag dependencies resolve at flag-matching time, never in HogQL; property_to_expr
            # treats them as neutral too.
            return None
        if property.type == "hogql":
            if from_test_accounts:
                raise QueryError(
                    "The team's test account filters include a SQL expression, which can't be applied "
                    "through {filters(...)} bindings. Turn off 'Filter out internal and test users' for this query."
                )
            raise QueryError(
                "SQL expression filters can't be applied through {filters(...)} bindings. "
                "Remove the SQL expression filter from the dashboard or insight."
            )
        if property.type in ("cohort", "static-cohort", "precalculated-cohort"):
            raise QueryError(
                "Cohort filters can't be applied through {filters(...)} bindings, because cohort "
                "membership is resolved per person. Remove the cohort filter from the dashboard or insight."
            )
        if property.type == "element":
            # Element filters match autocaptured DOM structure (selector regexes over elements_chain),
            # which a single bound column can't reproduce.
            raise QueryError(
                "Element filters match autocaptured elements and can't be applied through "
                "{filters(...)} bindings. Remove the element filter from the dashboard or insight."
            )
        if property.type == "recording":
            raise QueryError(
                "Session recording filters can't be applied through {filters(...)} bindings. "
                "Remove the recording filter from the dashboard or insight."
            )

        key = str(property.key)
        if key not in bindings:
            label = "test account filter" if from_test_accounts else "property filter"
            raise QueryError(
                f"The {label} on '{key}' has no binding in {{filters(...)}}. "
                f"Bind a column like {{filters(my_column AS '{key}')}} to apply it, "
                f"or null AS '{key}' to skip it."
            )
        bound_expr = bindings[key]
        if bound_expr is None:
            return None
        return bound_property_to_expr(property, bound_expr, self.team)

    def _replace_interval(self, args: list[ast.Expr]) -> ast.Expr:
        if len(args) > 1:
            raise QueryError(
                "{filters.interval(...)} takes at most one argument: the default interval, "
                "e.g. {filters.interval('week')}."
            )
        default = "day"
        if args:
            arg = args[0]
            if not isinstance(arg, ast.Constant) or arg.value not in INTERVAL_UNITS:
                units = ", ".join(sorted(INTERVAL_UNITS))
                raise QueryError(f"The default interval must be a constant string, one of: {units}.")
            default = arg.value
        if self.filters is not None and self.filters.interval is not None:
            return ast.Constant(value=self.filters.interval.value)
        return ast.Constant(value=default)

    def _replace_breakdown(self, args: list[ast.Expr]) -> ast.Expr:
        # Bindings are validated before checking whether a breakdown is set, so malformed usage
        # surfaces in the SQL editor even while no breakdown is selected yet.
        bindings = self._parse_binding_args(args, BOUND_BREAKDOWN_USAGE, "{filters.breakdown(...)}")
        breakdown_filter = self.filters.breakdownFilter if self.filters is not None else None
        key = self._resolve_breakdown_key(breakdown_filter)
        if key is None:
            # No breakdown selected: a constant key keeps the query valid and yields a single group.
            return ast.Constant(value=None)
        if key not in bindings:
            raise QueryError(
                f"The breakdown on '{key}' has no binding in {{filters.breakdown(...)}}. "
                f"Bind a column like {{filters.breakdown(my_column AS '{key}')}} to apply it, "
                f"or null AS '{key}' to skip it."
            )
        bound_expr = bindings[key]
        if bound_expr is None:
            return ast.Constant(value=None)
        return clone_expr(bound_expr)

    def _resolve_breakdown_key(self, breakdown_filter: Optional[BreakdownFilter]) -> Optional[str]:
        if breakdown_filter is None:
            return None
        if breakdown_filter.breakdowns:
            if len(breakdown_filter.breakdowns) > 1:
                raise self._multiple_breakdowns_error()
            single = breakdown_filter.breakdowns[0]
            if single.type == MultipleBreakdownType.COHORT:
                raise self._cohort_breakdown_error()
            if single.histogram_bin_count is not None:
                raise self._histogram_breakdown_error()
            return str(single.property)
        if breakdown_filter.breakdown is None:
            return None
        if breakdown_filter.breakdown_type == BreakdownType.COHORT:
            raise self._cohort_breakdown_error()
        if breakdown_filter.breakdown_histogram_bin_count is not None:
            raise self._histogram_breakdown_error()
        breakdown = breakdown_filter.breakdown
        if isinstance(breakdown, list):
            if len(breakdown) == 0:
                return None
            if len(breakdown) > 1:
                raise self._multiple_breakdowns_error()
            breakdown = breakdown[0]
        return str(breakdown)

    def _multiple_breakdowns_error(self) -> QueryError:
        return QueryError(
            "{filters.breakdown(...)} supports a single breakdown. "
            "Remove the extra breakdowns from the dashboard or insight."
        )

    def _cohort_breakdown_error(self) -> QueryError:
        return QueryError(
            "Cohort breakdowns can't be applied through {filters.breakdown(...)}, because cohort "
            "membership is resolved per person. Remove the cohort breakdown from the dashboard or insight."
        )

    def _histogram_breakdown_error(self) -> QueryError:
        return QueryError(
            "Numeric binning isn't supported by {filters.breakdown(...)}. Remove the bin count from the breakdown."
        )

    def _persons_test_account_filter_error(self, prop: Any) -> QueryError:
        # The filter comes from project settings rather than the query, so the bare scope error from
        # property_to_expr names something the reader never wrote and can't act on.
        prop_type = prop.get("type") if isinstance(prop, dict) else getattr(prop, "type", None)
        key = prop.get("key") if isinstance(prop, dict) else getattr(prop, "key", None)
        described = f"the {prop_type or 'unknown'} property filter" + (f" on '{key}'" if key else "")
        return QueryError(
            f"A test account filter in your project settings ({described}) can't apply to a query that "
            "selects only from persons. Change it to a person property filter in project settings, or "
            "bind it yourself with {filters(expr AS key, ...)}."
        )
