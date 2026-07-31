# Compiles a ticket group's `sql` filter — a HogQL boolean expression written
# by a customer in Settings → Support → Ticket groups — into a Postgres
# condition that can be ANDed into the tickets-list rank CASE (see
# ticket_groups.py).
#
# ## Why this works at all
#
# HogQL already knows how to describe support tickets: `system.support_tickets`
# (posthog/hogql/database/schema/system.py) maps HogQL field names onto the real
# columns of `posthog_conversations_ticket`, and carries `access_scope="ticket"`
# — the same APIScopeObject the ticket API uses — so reaching tickets through
# HogQL is governed by the same RBAC as reaching them over REST. HogQL also has
# a Postgres printer (posthog/hogql/printer/postgres.py), built for
# direct-query warehouse sources. We borrow both: resolve the expression
# against `system.support_tickets` aliased to `posthog_conversations_ticket`,
# then print just that expression in the Postgres dialect. Because the alias
# matches Django's base-table alias, the printed fragment drops straight into a
# queryset over Ticket.
#
# ## What we refuse, and why
#
# The printed fragment is spliced into SQL, so this module is a security
# boundary. Every value a customer writes is bound as a parameter by the
# printer (never interpolated), but that alone is not enough:
#
#   - SUBQUERIES: `system.*` tables print as ClickHouse's `postgresql(host,
#     db, table, user, password)` table function, which binds this
#     deployment's database credentials as query parameters. A subquery would
#     therefore drag the DB password into the tickets-list query (and into
#     anything that logs it). Rejected on the parsed AST, before any SQL exists.
#   - AGGREGATES / WINDOW FUNCTIONS: legal in a SELECT, illegal in a WHERE;
#     they would turn a bad config into a 500 on every tickets list.
#   - UNRESOLVED FIELDS: the Postgres dialect does NOT raise on unknown
#     columns — it records a notice on the context and prints the bare name,
#     which explodes at query time. So context.errors must be checked.
#
# And because compiling is not the same as being runnable, the write path also
# EXECUTES the fragment over a bounded sample of the team's tickets
# (_verify_executable). That is where non-boolean expressions, set-returning
# functions (generateSeries prints as generate_series, arrayJoin as UNNEST — both
# illegal inside a CASE/WHEN), type mismatches, and expressions that are only
# expensive or only fail once real data is involved get caught. Two of those are
# easy to miss:
#   - ClickHouse's JSON functions print as json_extract_path_text, which takes
#     `json` while our columns are `jsonb`, so
#     `JSONExtractString(session_context, 'plan')` compiles and cannot run. Use
#     chain access — `session_context.plan` — which prints as Postgres' native
#     -> / ->> operators.
#   - `repeat(email_from, 100000000)` plans fine (the planner can't fold a column
#     reference) and then allocates ~100MB per row at read time. Only evaluation
#     against rows reveals it.
# A statement_timeout bounds both the planning and the evaluation, and the read
# path carries its own (ticket_groups._filter_condition / LIST_QUERY_TIMEOUT_MS)
# because it cannot afford to re-verify per request.
#
# Two `system.support_tickets` fields cannot work in an expression and are
# reported as such: `tags` (a lazy join onto an aggregating subquery — the
# ticket_tags filter is the right tool, and can be ANDed alongside) and
# `ai_resolved` (an ExpressionField, only expanded inside a full SELECT).
#
# Tenant isolation is NOT provided here: the Postgres dialect intentionally
# emits no team_id predicate (posthog/hogql/printer/postgres.py —
# _ensure_team_id_where_clause is a no-op). It comes from the enclosing
# queryset, which is always team-scoped, plus the subquery ban above which
# leaves an expression no way to reach another table.
import re
from typing import Any, Optional, cast

from django.db import DataError, OperationalError, ProgrammingError, connection, transaction

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import ExpressionField, LazyJoin
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer.utils import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.property import has_aggregation
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import TraversingVisitor

from posthog.models.team import Team
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl

# The Django base-table alias for Ticket. The host SELECT is aliased to this so
# printed column references line up with the queryset the fragment lands in.
TICKET_TABLE_ALIAS = "posthog_conversations_ticket"

# Long enough for a real condition, short enough that a config's SQL filters
# can't bloat every tickets-list query (their number is capped separately, by
# ticket_groups.MAX_SQL_FILTERS). Mirrored in ticketGroups.ts as
# MAX_TICKET_GROUP_SQL_LENGTH.
MAX_SQL_EXPRESSION_LENGTH = 1000

# Django's RawSQL takes positional params; the HogQL printer emits named ones.
_NAMED_PARAM_REGEX = re.compile(r"%\((?P<name>[^)]+)\)s")

# Planning and evaluating a ticket predicate over a few rows is sub-millisecond
# work; anything approaching this is a resource bomb (see _verify_executable),
# not a real filter.
VERIFY_TIMEOUT_MS = 1000
# Enough rows to exercise real data (nulls, odd values) without making a settings
# save read a meaningful slice of a big team's table.
VERIFY_SAMPLE_ROWS = 100

# The read path can't afford to re-verify each filter, so it caps the whole rank
# query instead. Generous — a rank CASE over a page is milliseconds, and a
# tag-filtered count can legitimately take a while on a large team — but finite,
# so a data-dependent expression can't tie up a connection indefinitely.
LIST_QUERY_TIMEOUT_MS = 10_000

# SQLSTATEs that mean "this expression costs too much", as opposed to "the
# database is unwell". 57014 is query_canceled — our statement_timeout firing.
# Class 54 is program_limit_exceeded, which Postgres raises when it refuses an
# allocation outright ("requested length too large") before any timeout can fire.
# Both are the customer's expression; anything else operational is ours, and must
# not be blamed on them or silently degraded (see api/tickets.py).
_QUERY_CANCELED_SQLSTATE = "57014"
_PROGRAM_LIMIT_SQLSTATE_CLASS = "54"


def sqlstate_of(error: Exception) -> Optional[str]:
    """The SQLSTATE behind a Django database error. psycopg3 exposes `sqlstate`,
    psycopg2 `pgcode`; both are declared dependencies, so read either."""
    cause = getattr(error, "__cause__", None)
    return getattr(cause, "sqlstate", None) or getattr(cause, "pgcode", None)


def is_expression_too_expensive(error: Exception) -> bool:
    """Whether a database error says the expression itself was too costly to run."""
    sqlstate = sqlstate_of(error)
    if sqlstate is None:
        return False
    return sqlstate == _QUERY_CANCELED_SQLSTATE or sqlstate.startswith(_PROGRAM_LIMIT_SQLSTATE_CLASS)


class TicketGroupSqlError(Exception):
    """A `sql` ticket-group filter that can't be compiled. The message is shown
    to whoever is editing the groups, so it must read as guidance."""


class _VerificationDone(Exception):
    """Private signal used to roll back the verification transaction on success —
    see _verify_executable. Never escapes this module."""


class _UnsupportedConstructFinder(TraversingVisitor):
    """Constructs we refuse before resolving, so the offending SQL is never
    built (see the subquery/credentials note in the module docstring), plus
    references to fields that can't survive expression-only compilation."""

    def __init__(self, table_fields: dict[str, Any]) -> None:
        super().__init__()
        self.problems: list[str] = []
        self._table_fields = table_fields

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.problems.append("Subqueries aren't allowed in a SQL expression filter.")

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.problems.append("Subqueries aren't allowed in a SQL expression filter.")

    def visit_placeholder(self, node: ast.Placeholder) -> None:
        self.problems.append("Placeholders ({...}) aren't allowed in a SQL expression filter.")

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        self.problems.append("Window functions aren't allowed in a SQL expression filter.")

    def visit_field(self, node: ast.Field) -> None:
        # Classify from the table definition rather than a hardcoded name list,
        # so a new lazy join on system.support_tickets gets a clear message here
        # instead of an ImpossibleASTError at query time.
        name = str(node.chain[0])
        field = self._table_fields.get(name)
        if isinstance(field, LazyJoin):
            if name == "tags":
                self.problems.append(
                    "Tags aren't available in a SQL expression — add a Ticket tags filter to the same group instead."
                )
            else:
                self.problems.append(f"`{name}` isn't available in a SQL expression filter.")
        elif isinstance(field, ExpressionField):
            self.problems.append(
                f"`{name}` isn't available in a SQL expression filter — it's a derived field, "
                "so filter on the underlying columns instead."
            )


def build_ticket_group_sql_database(
    team: Team,
    user: Optional[User] = None,
    user_access_control: Optional[UserAccessControl] = None,
) -> Database:
    """The HogQL database used to resolve group expressions. Pass the request's
    already-preloaded UserAccessControl where there is one (the ticket viewset
    has it) so this costs no extra access-control query.

    Building it is not free, so callers should only do so when a config
    actually contains a `sql` filter — see ticket_groups.groups_use_sql.
    """
    return Database.create_for(team=team, user=user, user_access_control=user_access_control)


def _verify_executable(sql: str, params: list[Any], team_id: int) -> None:
    """Run the fragment, in the shape the rank annotation uses it, over a bounded
    sample of the team's real tickets. Compiling is NOT the same as being
    runnable, and there are two distinct ways to be unrunnable:

    - SHAPE. A set-returning function (generateSeries prints as generate_series,
      arrayJoin as UNNEST) type-checks as boolean and is then rejected with
      "argument of CASE/WHEN must not return a set"; a non-boolean expression
      gets "must be type boolean". Planning alone catches these.
    - DATA. `repeat(email_from, 100000000)` is fine to plan — the planner can't
      fold a column reference — and then allocates ~100MB PER ROW when the list
      is queried. Division by zero and casts that only fail on some values are
      the same story. Only evaluating against real rows catches these, which is
      why this executes rather than just EXPLAINing.

    `bool_or(CASE WHEN ...)` is load-bearing: `count(*)` over the same subquery
    silently passes, because Postgres never evaluates a column nothing reads.

    LIMIT bounds the work, and the statement_timeout bounds it again — the
    planner constant-folds immutable functions, so `repeat('a', 400000000) = 'x'`
    allocates 400MB during PLANNING, before any row is touched.

    A team with no tickets yet can't be sampled, so a data-dependent problem may
    still reach the list; ticket_groups' read path has the matching timeout and
    degrades rather than failing. The transaction is always rolled back: this is
    a read, so there's nothing to keep, and rolling back reverts the SET LOCAL on
    every path (a nested atomic's RELEASE SAVEPOINT would not) and stops a failed
    statement poisoning an enclosing transaction.
    """
    statement = (
        f"SELECT bool_or(CASE WHEN {sql} THEN true ELSE false END) FROM ("
        f"SELECT * FROM {TICKET_TABLE_ALIAS} WHERE team_id = %s LIMIT {VERIFY_SAMPLE_ROWS}"
        f") AS {TICKET_TABLE_ALIAS}"
    )
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"SET LOCAL statement_timeout = {VERIFY_TIMEOUT_MS}")
                # The fragment precedes the subquery in the statement, so its
                # params bind before team_id.
                cursor.execute(statement, [*params, team_id])
            raise _VerificationDone
    except _VerificationDone:
        return
    except OperationalError as error:
        # Our timeout firing, or Postgres refusing the allocation outright.
        # Anything else operational (connection loss, pool exhaustion) is OUR
        # problem, not the customer's — let it propagate rather than blaming their
        # expression, and note that its message can carry the database host/port.
        if not is_expression_too_expensive(error):
            raise
        raise TicketGroupSqlError(
            "That SQL expression is too expensive to evaluate — simplify it "
            "(very large generated values are the usual cause)."
        )
    except (ProgrammingError, DataError) as error:
        # Only the syntax/type/undefined-function family means "your expression
        # is wrong". Connection and timeout failures are DatabaseError too, and
        # blaming those on the customer's expression would send them chasing a
        # bug that isn't there — those propagate as a 500, which is honest.
        detail = str(error).strip().splitlines()[0]
        raise TicketGroupSqlError(f"Postgres rejected that SQL expression: {detail}")


def compile_ticket_group_sql(
    expression: str, database: Database, team_id: int, verify_executable: bool = True
) -> tuple[str, list[Any]]:
    """Compile a HogQL boolean expression into a (sql_fragment, params) pair for
    Django's RawSQL, against `TICKET_TABLE_ALIAS`.

    Raises TicketGroupSqlError for anything we won't run — the write validator
    surfaces that to the editor, and the read path treats it as "matches
    nothing" rather than failing the whole list.

    `verify_executable` defaults to on so any new caller gets the safe
    behaviour; the read path turns it off because it has already been checked at
    write time and a DB round trip per filter per request is too expensive.
    """
    if not expression or not expression.strip():
        raise TicketGroupSqlError("A SQL expression filter can't be empty.")
    if len(expression) > MAX_SQL_EXPRESSION_LENGTH:
        raise TicketGroupSqlError(f"SQL expression is too long (max {MAX_SQL_EXPRESSION_LENGTH} characters).")

    context = HogQLContext(team_id=team_id, database=database, enable_select_queries=True)
    try:
        node = parse_expr(expression)

        ticket_table = database.get_table("system.support_tickets")
        finder = _UnsupportedConstructFinder(ticket_table.fields)
        finder.visit(node)
        if finder.problems:
            raise TicketGroupSqlError(finder.problems[0])

        # A resolved host SELECT supplies the scope the expression resolves
        # against; aliasing it to the Django table name makes the printed
        # column references match the queryset this fragment lands in.
        # A plain SELECT in, so a resolved SelectQuery out.
        host = cast(
            ast.SelectQuery,
            prepare_ast_for_printing(
                # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql
                # (HogQL's parser, not a database cursor; the only interpolation is
                # this module's own TICKET_TABLE_ALIAS constant)
                parse_select(f"SELECT 1 FROM system.support_tickets AS {TICKET_TABLE_ALIAS}"),
                context=context,
                dialect="postgres",
            ),
        )
        resolved = resolve_types(node, context, dialect="postgres", scopes=[cast(ast.SelectQueryType, host.type)])

        if has_aggregation(resolved):
            raise TicketGroupSqlError("Aggregate functions (like count()) can't be used in a SQL expression filter.")

        # NOTE: no static boolean-type check here. HogQL types plenty of genuinely
        # boolean expressions as something else (`if(...)`, `multiIf(...)`,
        # `startsWith(...)`, `empty(...)`), so requiring ast.BooleanType rejected
        # working conditions. _verify_executable settles it instead: Postgres says
        # "argument of CASE/WHEN must be type boolean" for a real non-boolean,
        # which is both stricter where it counts and more accurate to report.
        sql = print_prepared_ast(resolved, context=context, dialect="postgres", stack=[host])
    except BaseHogQLError as error:
        raise TicketGroupSqlError(str(error))

    # The Postgres dialect records unknown columns as notices instead of
    # raising, then prints the bare name — which would fail at query time.
    if context.errors:
        raise TicketGroupSqlError(context.errors[0].message)

    named_values = context.values
    if any("sensitive" in name for name in named_values):
        # Unreachable while subqueries are rejected; keeps it that way.
        raise TicketGroupSqlError("That SQL expression isn't supported here.")

    fragment, params = _to_positional_params(sql, named_values)
    if verify_executable:
        _verify_executable(fragment, params, team_id)
    return fragment, params


def _to_positional_params(sql: str, named_values: dict[str, Any]) -> tuple[str, list[Any]]:
    """Rewrite the printer's %(name)s placeholders to Django's positional %s,
    collecting values in the order they appear (a value used twice is bound
    twice)."""
    params: list[Any] = []

    def replace(match: re.Match) -> str:
        name = match.group("name")
        if name not in named_values:
            raise TicketGroupSqlError("That SQL expression isn't supported here.")
        params.append(named_values[name])
        return "%s"

    return _NAMED_PARAM_REGEX.sub(replace, sql), params
