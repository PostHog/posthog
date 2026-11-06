"""Decide whether a run gets analyzed, print its SQL, and enqueue the job.

The runner calls this once per blocking run. The SQL is printed only for a run over the flag's
``floor_ms`` or one ClickHouse stopped. A printer, broker or Redis failure drops the enqueue, never
the query result.
"""

from __future__ import annotations

import copy
from typing import Any, Literal, TypeGuard

import structlog
from pydantic import BaseModel

from posthog.schema import (
    BaseMathType,
    BreakdownType,
    EventsNode,
    FunnelMathType,
    GroupMathType,
    LifecycleQuery,
    NodeKind,
    RetentionType,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.query_stats import QueryStats, RecordedExecution

from posthog.clickhouse.query_tagging import Feature, get_query_tag_value, is_api_key_access_method
from posthog.event_usage import EventSource
from posthog.models.user import User
from posthog.query_scan.event_filter import classify_event_filter
from posthog.query_scan.explain import EXPLAIN_MAX_SECONDS
from posthog.query_scan.findings import SQL_QUERY_KIND
from posthog.query_scan.flag import QueryScanFlag
from posthog.query_scan.slot import (
    claim_enqueue_budget,
    clear as clear_slot,
    get as get_slot,
    set_pending,
)
from posthog.query_scan.stub import stub_in_subqueries
from posthog.query_scan.tree import EventsRead, find_events_reads
from posthog.query_scan.tree_facts import tree_facts

logger = structlog.get_logger(__name__)

# The runner can fan an insight out into many series; the heaviest handful explains the run.
MAX_EXECUTIONS = 5
# Each subquery is explained on its own, so the cap is across the whole run, not per execution.
MAX_SUBQUERIES = 5

# Math that finds each person's or group's first event, so the read has to start at the project's
# first event whatever date range the insight has.
_FIRST_TIME_MATHS: frozenset[str] = frozenset(
    {
        BaseMathType.FIRST_TIME_FOR_USER,
        BaseMathType.FIRST_MATCHING_EVENT_FOR_USER,
        GroupMathType.FIRST_TIME_FOR_GROUP,
        GroupMathType.FIRST_MATCHING_EVENT_FOR_GROUP,
        FunnelMathType.FIRST_TIME_FOR_USER,
        FunnelMathType.FIRST_TIME_FOR_USER_WITH_FILTERS,
    }
)

# Math that counts people or sessions over whatever they did, so on an "All events" series the
# answer needs every event and picking events would change it.
_ANY_EVENT_MATHS: frozenset[str] = frozenset(
    {
        BaseMathType.DAU,
        BaseMathType.WEEKLY_ACTIVE,
        BaseMathType.MONTHLY_ACTIVE,
        BaseMathType.UNIQUE_SESSION,
    }
)

# Every other kind belongs to a PostHog screen that shows no advice and has nothing to edit.
_KINDS_A_PERSON_BUILDS: frozenset[str] = frozenset(
    {
        NodeKind.HOG_QL_QUERY,
        NodeKind.TRENDS_QUERY,
        NodeKind.FUNNELS_QUERY,
        NodeKind.RETENTION_QUERY,
        NodeKind.LIFECYCLE_QUERY,
        NodeKind.PATHS_QUERY,
        NodeKind.STICKINESS_QUERY,
    }
)
# PostHog's own screens run SQL too, so the kind alone does not say a person wrote it.
_SQL_SCENES_WITH_ADVICE: frozenset[str] = frozenset({"SQLEditor", "Insight"})

SkipReason = Literal[
    "flag_off",
    "below_floor",
    "api_key",
    "mcp",
    "kind_not_analyzed",
    "sql_without_surface",
    "no_principal",
    "no_clickhouse_query",
    "not_cacheable",
    "direct_connection",
    "sensitive_values",
    "rate_limited",
    "slot_exists",
    "nothing_to_analyze",
    "print_failed",
    "enqueue_failed",
]


def _is_mcp_run() -> bool:
    """Whether an MCP agent made the run. A PostHog AI tool the MCP server invokes carries the
    feature. A call the server proxies to the query endpoint carries the source the request
    middleware set, whichever key or token the agent authenticates with."""
    return get_query_tag_value("feature") == Feature.MCP or get_query_tag_value("source") == EventSource.MCP


def _sql_run_has_surface(insight_id: int | None, dashboard_id: int | None) -> bool:
    if insight_id or dashboard_id:
        return True
    return get_query_tag_value("scene") in _SQL_SCENES_WITH_ADVICE


def is_analyzable_principal(user: object) -> TypeGuard[User]:
    """Whether the response may carry the scan summary. Only a real user row is a member of the project;
    a shared-link viewer must not see the project's data volume.
    """
    return isinstance(user, User)


def maybe_trigger_query_scan(
    *,
    flag: QueryScanFlag | None,
    stats: QueryStats | None,
    team_id: int,
    cache_key: str,
    query: BaseModel,
    trigger: str,
    cacheable: bool,
    insight_id: int | None = None,
    dashboard_id: int | None = None,
    killed: bool = False,
    error_type: str | None = None,
) -> SkipReason | None:
    """Enqueue the analysis for this run. Returns why it was skipped, or None once the job is enqueued."""
    if flag is None or stats is None:
        return "flag_off"

    # A lookup a runner made on the way to its real query, such as the project's first event for
    # an All time range, is not the query the person wrote, so it neither counts toward the floor
    # nor gets analyzed in the query's place. The totals cover raw lookups too, which never reach
    # the executor and so are never recorded as executions.
    executions = [execution for execution in stats.executions if execution.lookup is None]
    rows_read = max(0, stats.rows_read - stats.lookup_rows_read)
    duration_ms = max(0, round(stats.duration_ms - stats.lookup_duration_ms))
    # The floor leaves alone the runs nobody minded. Nobody gets a result from a run ClickHouse
    # stopped, however fast it died, so a stopped run is analyzed at any duration.
    if duration_ms < flag.floor_ms and not killed:
        return "below_floor"
    if _is_mcp_run():
        # Nothing hands an agent the advice, so the analysis would only cost.
        return "mcp"
    if is_api_key_access_method(get_query_tag_value("access_method")):
        # An API caller has no surface to read the advice on, so the analysis would only cost.
        return "api_key"
    kind = getattr(query, "kind", None)
    query_kind = str(kind) if kind is not None else None
    if query_kind not in _KINDS_A_PERSON_BUILDS:
        return "kind_not_analyzed"
    if query_kind == SQL_QUERY_KIND and not _sql_run_has_surface(insight_id, dashboard_id):
        return "sql_without_surface"
    if getattr(query, "connectionId", None):
        # A direct connection reads the external warehouse instead of ClickHouse, so the job
        # would park a pending slot for an analysis that cannot happen.
        return "direct_connection"
    if not cacheable:
        return "not_cacheable"
    if get_slot(team_id, cache_key, thresholds=flag.thresholds_fingerprint) is not None:
        return "slot_exists"
    if not claim_enqueue_budget(team_id):
        return "rate_limited"
    if not set_pending(team_id, cache_key, thresholds=flag.thresholds_fingerprint):
        # Another slow run of the same query claimed the slot between the read above and here.
        return "slot_exists"

    printed = _print_executions(executions)
    if isinstance(printed, str):
        # A selected execution could not be shipped, so analyzing the rest would advise on a run the
        # job never saw whole.
        clear_slot(team_id, cache_key, thresholds=flag.thresholds_fingerprint)
        return printed
    if not printed:
        # The run had no executions to print: it bypassed the executor, or fanned out into none.
        clear_slot(team_id, cache_key, thresholds=flag.thresholds_fingerprint)
        return "nothing_to_analyze"

    # A module-level import would close the runner, trigger, task, job, runner cycle.
    from posthog.tasks.query_scan import analyze_query_scan  # noqa: PLC0415

    try:
        analyze_query_scan.delay(
            team_id=team_id,
            cache_key=cache_key,
            executions=printed,
            rows_read=rows_read,
            duration_ms=duration_ms,
            trigger=trigger,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
            killed=killed,
            error_type=error_type,
            query_kind=query_kind,
            open_filters_placeholder=_open_filters_placeholder(query),
            all_time=_all_time(query),
            dashboard_all_time=get_query_tag_value("dashboard_all_time") is True,
            all_history_by_design=_reads_all_history_by_design(query),
            all_events_by_design=_reads_all_events_by_design(query),
        )
    except Exception:
        # The broker can be down while ClickHouse is fine, and the result is not cached yet, so
        # failing here would throw away a run the person already waited for.
        logger.warning("query_scan_enqueue_failed", team_id=team_id, exc_info=True)
        # Left in place, the claim above reports a pending analysis no job is coming to fill.
        clear_slot(team_id, cache_key, thresholds=flag.thresholds_fingerprint)
        return "enqueue_failed"
    return None


def _print_executions(executions: list[RecordedExecution]) -> list[dict[str, Any]] | SkipReason:
    """Print the heaviest executions for the job to EXPLAIN: each with its subqueries stubbed, and
    each subquery on its own. The skip reason when any of the heaviest could not be shipped, so the
    job never analyzes part of a run and advises as if it saw the whole. An empty list means the run
    carried no executions to print.
    """
    heaviest = sorted(executions, key=lambda execution: execution.rows_read, reverse=True)[:MAX_EXECUTIONS]
    printed: list[dict[str, Any]] = []
    subquery_budget = MAX_SUBQUERIES
    for execution in heaviest:
        entry = _print_execution(execution, subquery_budget)
        if isinstance(entry, str):
            return entry
        subquery_budget -= len(entry["subqueries"])
        printed.append(entry)
    return printed


def _print_execution(execution: RecordedExecution, subquery_budget: int) -> dict[str, Any] | SkipReason:
    """One execution as the job's payload entry, or why it cannot be shipped."""
    try:
        # The run's context still holds every value the run printed, credentials included.
        context = copy.copy(execution.context)
        context.values = {}
        stub = stub_in_subqueries(execution.tree)
        # A setting in the SQL overrides the one the job passes, so the EXPLAIN's time limit goes here.
        settings = (
            execution.settings.model_copy(update={"max_execution_time": EXPLAIN_MAX_SECONDS})
            if execution.settings is not None
            else None
        )
        # Each plan is judged on the reads it holds: a subquery's on its own, the outer query's
        # without any of them. The tree is the run's, so the subqueries are the nodes inside it.
        subquery_reads = [find_events_reads(subquery) for subquery in stub.subqueries]
        in_a_subquery = {id(read.select) for reads in subquery_reads for read in reads}
        outer_reads = [read for read in find_events_reads(execution.tree) if id(read.select) not in in_a_subquery]
        entry = {
            "stubbed_sql": print_prepared_ast(stub.stubbed, context, dialect="clickhouse", settings=settings),
            "subqueries": [
                {
                    "sql": print_prepared_ast(
                        stub_in_subqueries(subquery).stubbed, context, dialect="clickhouse", settings=settings
                    ),
                    "event_filter": _event_filter_verdict(execution.tree, reads),
                    "tree": _tree_facts_payload(execution.tree, reads),
                }
                for subquery, reads in zip(stub.subqueries[: max(subquery_budget, 0)], subquery_reads)
            ],
            # The parameter values travel as they are: Celery's JSON serializer round-trips the
            # datetimes, dates, UUIDs and decimals among them.
            "values": context.values,
            "rows_read": execution.rows_read,
            # The plan says whether ClickHouse pruned on `event`; the tree says why it could not.
            # Classify here, where the prepared tree is held; the job folds it into the plan.
            "event_filter": _event_filter_verdict(execution.tree, outer_reads),
            "tree": _tree_facts_payload(execution.tree, outer_reads),
        }
        if any(key.endswith("_sensitive") for key in context.values):
            # The warehouse stub runs before the print, so this catches any other credential or access list.
            return "sensitive_values"
        return entry
    except Exception:
        # A tree that will not print is one the job could not EXPLAIN either. Dropping it drops the
        # run's analysis, never the query result the person already waited for.
        logger.warning("query_scan_print_failed", exc_info=True)
        return "print_failed"


def _event_filter_verdict(tree: ast.Expr, reads: list[EventsRead]) -> dict[str, str | bool | None] | None:
    """The tree's event-filter classification, JSON-safe, for the job to combine with the plan.

    A classifier failure ships None rather than dropping the execution, because the plan-only
    fallback still produces a finding. Reads that disagree ship None for the same reason.
    """
    try:
        outcome = classify_event_filter(tree, reads)
    except Exception:
        logger.warning("query_scan_classify_failed", exc_info=True)
        return None
    if outcome is None:
        return None
    return {
        "classification": outcome.classification,
        "reason": outcome.reason,
        "hidden_from_plan": outcome.hidden_from_plan,
    }


def _tree_facts_payload(tree: ast.Expr, reads: list[EventsRead]) -> dict[str, Any] | None:
    """What the tree says about its events reads, JSON-safe. A failure ships None rather than
    dropping the execution: the plan alone still yields a finding, with the plain wording."""
    try:
        facts = tree_facts(tree, reads)
    except Exception:
        logger.warning("query_scan_tree_facts_failed", exc_info=True)
        return None
    return facts.to_payload() if facts is not None else None


def _source(query: BaseModel) -> BaseModel:
    """The query an insight node wraps, or the query itself."""
    return getattr(query, "source", None) or query


def _all_time(query: BaseModel) -> bool:
    """Whether the person chose the "All time" date range. The runner turns that into a bound at
    the project's first event, so the plan reports a timestamp filter and cannot tell on its own."""
    source = _source(query)
    date_range = getattr(source, "dateRange", None)
    if date_range is None:
        filters = getattr(source, "filters", None)
        date_range = getattr(filters, "dateRange", None)
    return getattr(date_range, "date_from", None) == "all"


def _reads_all_history_by_design(query: BaseModel) -> bool:
    """Whether the insight has to read from the project's first event whatever its date range: a
    first-time math or first-time retention finds each person's first event, so a start date would
    change the answer and no start-date advice can help.
    """
    source = _source(query)
    series = getattr(source, "series", None) or []
    if any(getattr(item, "math", None) in _FIRST_TIME_MATHS for item in series):
        return True
    retention_filter = getattr(source, "retentionFilter", None)
    return getattr(retention_filter, "retentionType", None) == RetentionType.RETENTION_FIRST_TIME


def _reads_all_events_by_design(query: BaseModel) -> bool:
    """Whether the insight has to read every event whatever its series: an active-user, unique-session
    or lifecycle count on All events counts people over whatever they did, and a breakdown by event
    name is a question about the set of events itself. Picking events would change the answer.
    """
    source = _source(query)
    series = getattr(source, "series", None) or []
    all_events = [item for item in series if isinstance(item, EventsNode) and item.event is None]
    if not all_events:
        return False
    if any(getattr(item, "math", None) in _ANY_EVENT_MATHS for item in all_events):
        return True
    if isinstance(source, LifecycleQuery):
        return True
    breakdown_filter = getattr(source, "breakdownFilter", None)
    if breakdown_filter is None:
        return False
    if (
        getattr(breakdown_filter, "breakdown_type", None) == BreakdownType.EVENT_METADATA
        and getattr(breakdown_filter, "breakdown", None) == "event"
    ):
        return True
    return any(
        getattr(breakdown, "type", None) == BreakdownType.EVENT_METADATA
        and getattr(breakdown, "property", None) == "event"
        for breakdown in getattr(breakdown_filter, "breakdowns", None) or []
    )


def _open_filters_placeholder(query: BaseModel) -> bool:
    """Whether a HogQLQuery asks for a date range through ``{filters}`` and nobody supplied a start
    date. Only the predicate forms count: ``{filters.interval(...)}`` and ``{filters.breakdown(...)}``
    substitute a value and cannot bound the query. False for every other kind, which carries no raw SQL.
    """
    if getattr(query, "kind", None) != SQL_QUERY_KIND:
        return False
    try:
        if not find_placeholders(parse_select(getattr(query, "query", "") or "")).has_date_filters:
            return False
    except Exception:
        return False
    date_range = getattr(getattr(query, "filters", None), "dateRange", None)
    date_from = getattr(date_range, "date_from", None)
    # "all" promises the whole table, so the placeholder still expands to no lower bound, and an end
    # date on its own bounds nothing at the start.
    return not date_from or date_from == "all"
