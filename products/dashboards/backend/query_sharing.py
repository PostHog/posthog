from collections.abc import Iterable, Iterator
from concurrent.futures import CancelledError, Future
from contextlib import contextmanager
from dataclasses import field
from threading import Event, Lock
from uuid import uuid4

from prometheus_client import Counter

from posthog.schema import HogQLQueryResponse

from posthog.hogql import query_stats
from posthog.hogql.multi_query import ExecutionGroup, SharingQuery
from posthog.hogql.multi_query_execution import MultiQueryExecutor, SeparateOutcome, SharedOutcome
from posthog.hogql.query import HogQLQueryExecutor

from posthog.dataclasses import frozen

from products.dashboards.backend.facade.enums import DashboardSharingOutcome
from products.dashboards.backend.query_sharing_debug import sharing_debug

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
    tile_id: int | None = None
    shared_failed: Event = field(default_factory=Event)
    stats: query_stats.QueryStats | None = field(default_factory=query_stats.get_active)


@contextmanager
def _forward_query_starts(members: Iterable[_WaitingQuery]) -> Iterator[None]:
    running = query_stats.get_active()
    member_scopes = [member.stats for member in members if member.stats is not None and member.stats is not running]
    if running is None or not member_scopes:
        yield
        return

    def forward() -> None:
        for scope in member_scopes:
            scope.notify_query_started()

    running.query_start_listeners.append(forward)
    try:
        yield
    finally:
        running.query_start_listeners.remove(forward)


class DashboardQuerySharing:
    def __init__(self, *, match_window_seconds: float | None = None) -> None:
        self.cancelled = Event()
        self._lock = Lock()
        self._pending: dict[str, _WaitingQuery] = {}
        self._scope = str(uuid4())
        self._match_window_seconds = MATCH_WINDOW_SECONDS if match_window_seconds is None else match_window_seconds
        self._multi_query = MultiQueryExecutor(cancelled=self.cancelled)

    def cancel(self) -> None:
        self.cancelled.set()
        with self._lock:
            for waiting in self._pending.values():
                waiting.result.set_result(None)
            self._pending.clear()

    def _execute_separately(self, executor: HogQLQueryExecutor, reason: str) -> HogQLQueryResponse:
        if self.cancelled.is_set():
            raise CancelledError()
        SHARING_EXECUTIONS.labels(outcome="separate").inc()
        if debug := sharing_debug.get():
            debug.record(outcome=DashboardSharingOutcome.SEPARATE, tile_ids=[debug.tile_id], reason=reason)
        return executor.execute()

    def execute(self, executor: HogQLQueryExecutor) -> HogQLQueryResponse:
        if self.cancelled.is_set():
            raise CancelledError()
        query_id = str(uuid4())
        query = self._multi_query.prepare(executor, query_id=query_id, scope_key=self._scope)
        if isinstance(query, SeparateOutcome):
            return self._execute_separately(executor, query.reason)

        debug = sharing_debug.get()
        waiting = _WaitingQuery(query=query, result=Future(), tile_id=debug.tile_id if debug else None)
        group: ExecutionGroup | None = None
        members: dict[str, _WaitingQuery] = {}
        with self._lock:
            if self.cancelled.is_set():
                raise CancelledError()
            self._pending[query_id] = waiting
            plan = self._multi_query.plan([entry.query for entry in self._pending.values()])
            group = next((g for g in plan.groups if len(g.query_ids) > 1 and query_id in g.query_ids), None)
            if group:
                members = {member: self._pending.pop(member) for member in group.query_ids}

        if group:
            try:
                with _forward_query_starts(members.values()):
                    outcomes = self._multi_query.execute_group(executor, group)
            except Exception:
                # Cancellation also lands here, and each member's separate retry then raises CancelledError.
                outcomes = {}
            responses = {
                member: outcome.response for member, outcome in outcomes.items() if isinstance(outcome, SharedOutcome)
            }
            tile_ids = [entry.tile_id for entry in members.values() if entry.tile_id is not None]
            if responses.keys() == members.keys():
                SHARING_EXECUTIONS.labels(outcome="shared").inc()
                if debug:
                    debug.record(outcome=DashboardSharingOutcome.SHARED, tile_ids=tile_ids, rule=group.rule)
                for member, entry in members.items():
                    entry.result.set_result(responses[member])
            else:
                SHARING_EXECUTIONS.labels(outcome="fallback").inc()
                if debug:
                    debug.record(
                        outcome=DashboardSharingOutcome.FALLBACK,
                        tile_ids=tile_ids,
                        rule=group.rule,
                        reason="Shared execution failed; each tile retries independently.",
                    )
                for entry in members.values():
                    entry.shared_failed.set()
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
            return self._execute_separately(
                executor,
                "Retry after a failed shared execution."
                if waiting.shared_failed.is_set()
                else "No compatible query arrived within the matching window.",
            )
        return result.model_copy(
            update={
                "query": executor.query if isinstance(executor.query, str) else None,
                "hogql": executor.hogql,
                "modifiers": executor.query_modifiers,
                "limit": executor.limit,
                "offset": executor.offset,
            }
        )
