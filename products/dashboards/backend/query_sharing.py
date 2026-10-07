from concurrent.futures import CancelledError, Future
from dataclasses import replace
from threading import Event, Lock
from uuid import uuid4

from prometheus_client import Counter

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.batch import BatchQueryResult
from posthog.hogql.multi_query import ExecutionGroup, MultiQueryPlanner, SharingQuery
from posthog.hogql.query import HogQLQueryExecutor
from posthog.hogql.sharing_rules import CountFusionRule, SameAggregationTopNRule
from posthog.hogql.visitor import clone_expr

from posthog.dataclasses import frozen

SHARING_EXECUTIONS = Counter(
    "posthog_dashboard_sharing_executions_total",
    "Dashboard query executions by sharing outcome",
    ["outcome"],
)
MATCH_WINDOW_SECONDS = 0.05


@frozen
class _WaitingQuery:
    query: SharingQuery
    result: Future[HogQLQueryResponse | None]


class DashboardQuerySharing:
    def __init__(self, *, match_window_seconds: float | None = None) -> None:
        self.cancelled = Event()
        self._lock = Lock()
        self._pending: dict[str, _WaitingQuery] = {}
        self._scope = str(uuid4())
        self._match_window_seconds = MATCH_WINDOW_SECONDS if match_window_seconds is None else match_window_seconds
        self._planner = MultiQueryPlanner([SameAggregationTopNRule(), CountFusionRule()])

    def cancel(self) -> None:
        self.cancelled.set()
        with self._lock:
            for waiting in self._pending.values():
                waiting.result.set_result(None)
            self._pending.clear()

    def _execute_separately(self, executor: HogQLQueryExecutor) -> HogQLQueryResponse:
        if self.cancelled.is_set():
            raise CancelledError()
        SHARING_EXECUTIONS.labels(outcome="separate").inc()
        return executor.execute()

    @staticmethod
    def _unlimit_scalar_count(query: SharingQuery) -> SharingQuery:
        node = query.query
        if (
            isinstance(node, ast.SelectQuery)
            and not node.group_by
            and (node.offset is None or (isinstance(node.offset, ast.Constant) and node.offset.value == 0))
            and not node.limit_percent
            and not node.limit_with_ties
            and isinstance(node.limit, ast.Constant)
            and type(node.limit.value) is int
            and node.limit.value > 0
        ):
            unbounded = clone_expr(node)
            unbounded.limit = None
            unbounded.offset = None
            candidate = replace(query, query=unbounded)
            probe = MultiQueryPlanner([CountFusionRule()]).plan(
                [candidate, replace(candidate, query_id=f"{query.query_id}-probe")]
            )
            # A scalar count always returns one row, so the runner's pagination limit cannot affect it.
            if probe.groups:
                return candidate
        return query

    @staticmethod
    def _execute_group(executor: HogQLQueryExecutor, group: ExecutionGroup) -> dict[str, HogQLQueryResponse]:
        settings = executor.clickhouse_settings.model_copy() if executor.clickhouse_settings else None
        if settings is not None:
            settings.read_overflow_mode = "throw"
            settings.timeout_overflow_mode = "throw"
        shared = HogQLQueryExecutor(
            query=clone_expr(group.query),
            team=executor.team,
            user=executor.user,
            user_access_control=executor.context.user_access_control,
            modifiers=executor.query_modifiers,
            settings=settings,
            workload=executor.workload,
            ch_user=executor.ch_user,
            limit_context=executor.limit_context,
        ).execute()
        if shared.error or shared.hasMore or shared.results is None or shared.types is None:
            raise ValueError("Incomplete shared query result")
        split = group.split(
            BatchQueryResult(
                columns=tuple(shared.columns or []),
                types=tuple(column[1] for column in shared.types),
                rows=tuple(tuple(row) for row in shared.results),
            )
        )
        return {
            query_id: shared.model_copy(
                update={
                    "results": list(result.rows),
                    "columns": list(result.columns),
                    "types": list(zip(result.columns, result.types)),
                }
            )
            for query_id, result in split.items()
        }

    def execute(self, executor: HogQLQueryExecutor) -> HogQLQueryResponse:
        if self.cancelled.is_set():
            raise CancelledError()
        if executor.query_type != "HogQLQuery" or executor.connection_id or executor.send_raw_query:
            return self._execute_separately(executor)
        query_id = str(uuid4())
        original_query = clone_expr(executor.query) if isinstance(executor.query, ast.AST) else executor.query
        eligible = False
        try:
            query = executor.prepare_for_sharing(query_id=query_id, scope_key=self._scope)
            query = self._unlimit_scalar_count(query)
            # An identical partner probes eligibility without waiting on unsupported queries.
            probe = self._planner.plan([query, replace(query, query_id=f"{query_id}-probe")])
            eligible = len(probe.groups) == 1
        except Exception:
            eligible = False
        finally:
            executor.query = original_query
        if not eligible:
            return self._execute_separately(executor)

        waiting = _WaitingQuery(query=query, result=Future())
        group: ExecutionGroup | None = None
        members: dict[str, _WaitingQuery] = {}
        with self._lock:
            if self.cancelled.is_set():
                raise CancelledError()
            self._pending[query_id] = waiting
            plan = self._planner.plan([entry.query for entry in self._pending.values()])
            group = next((g for g in plan.groups if len(g.query_ids) > 1 and query_id in g.query_ids), None)
            if group:
                members = {member: self._pending.pop(member) for member in group.query_ids}

        if group:
            try:
                if self.cancelled.is_set():
                    raise CancelledError()
                results = self._execute_group(executor, group)
                SHARING_EXECUTIONS.labels(outcome="shared").inc()
                for member, entry in members.items():
                    entry.result.set_result(results[member])
            except Exception:
                SHARING_EXECUTIONS.labels(outcome="fallback").inc()
                for entry in members.values():
                    entry.result.set_result(None)
        else:
            try:
                waiting.result.result(timeout=self._match_window_seconds)
            except TimeoutError:
                with self._lock:
                    if self._pending.pop(query_id, None) is not None:
                        waiting.result.set_result(None)

        result = waiting.result.result()
        if result is None:
            return self._execute_separately(executor)
        return result.model_copy(
            update={
                "query": executor.query if isinstance(executor.query, str) else None,
                "hogql": executor.hogql,
                "modifiers": executor.query_modifiers,
                "limit": executor.limit,
                "offset": executor.offset,
            }
        )
