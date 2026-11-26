import dataclasses
from collections.abc import Sequence
from concurrent.futures import CancelledError
from dataclasses import replace
from threading import Event

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.batch import BatchQueryResult
from posthog.hogql.constants import LimitContext, get_max_limit_for_context
from posthog.hogql.multi_query import ExecutionGroup, MultiQueryPlanner, SharingPlan, SharingQuery, SharingRule
from posthog.hogql.query import HogQLQueryExecutor
from posthog.hogql.sharing_rules import CountFusionRule, SameAggregationTopNRule
from posthog.hogql.visitor import clone_expr

from posthog.dataclasses import frozen

UNSUPPORTED_EXECUTOR_REASON = "This query type or connection does not support sharing."
NO_SHARING_RULE_REASON = "No sharing rule supports this query shape or context."
SHARED_EXECUTION_FAILED_REASON = "The shared query failed or returned an incomplete result."


@frozen
class SharedOutcome:
    query_id: str
    rule: str
    # Holds only this query's rows. The shared SQL and metadata stay out because they contain every member's predicates.
    response: HogQLQueryResponse


@frozen
class SeparateOutcome:
    query_id: str
    reason: str


@frozen
class FallbackOutcome:
    query_id: str
    rule: str
    reason: str


QueryOutcome = SharedOutcome | SeparateOutcome | FallbackOutcome


@dataclasses.dataclass(frozen=False, kw_only=True)
class _CancellableExecutor(HogQLQueryExecutor):
    cancelled: Event | None = None

    def _execute_clickhouse_query(self) -> None:
        # Compiling takes long enough that a disconnect can arrive before ClickHouse knows the query ID to kill.
        if self.cancelled is not None and self.cancelled.is_set():
            raise CancelledError()
        super()._execute_clickhouse_query()


class MultiQueryExecutor:
    """Run several HogQL queries together, sharing one ClickHouse query wherever a sharing rule allows it.

    Planning only groups queries whose `SharingQuery.context_key` matches, so any member's executor
    can run its group. Callers stay responsible for authorizing each query before they prepare it.
    """

    def __init__(self, *, rules: Sequence[SharingRule] | None = None, cancelled: Event | None = None) -> None:
        self.cancelled = cancelled if cancelled is not None else Event()
        self._planner = MultiQueryPlanner(
            rules if rules is not None else [SameAggregationTopNRule(), CountFusionRule()]
        )

    @staticmethod
    def _lift_pagination_limit(query: SharingQuery) -> SharingQuery:
        node = query.query
        if (
            isinstance(node, ast.SelectQuery)
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
            # A scalar count returns one row, so only grouped counts need the runner's page size applied after routing.
            candidate = replace(query, query=unbounded, default_limit=node.limit.value if node.group_by else None)
            probe = MultiQueryPlanner([CountFusionRule()]).plan(
                [candidate, replace(candidate, query_id=f"{query.query_id}-probe")]
            )
            if len(probe.groups) == 1:
                return candidate
        return query

    def prepare(self, executor: HogQLQueryExecutor, *, query_id: str, scope_key: str) -> SharingQuery | SeparateOutcome:
        if executor.query_type != "HogQLQuery" or executor.connection_id or executor.send_raw_query:
            return SeparateOutcome(query_id=query_id, reason=UNSUPPORTED_EXECUTOR_REASON)
        original_query = clone_expr(executor.query) if isinstance(executor.query, ast.AST) else executor.query
        try:
            query = self._lift_pagination_limit(executor.prepare_for_sharing(query_id=query_id, scope_key=scope_key))
            # An identical partner probes eligibility without waiting on unsupported queries.
            probe = self._planner.plan([query, replace(query, query_id=f"{query_id}-probe")])
            eligible = len(probe.groups) == 1
        except Exception:
            eligible = False
        finally:
            executor.query = original_query
        if not eligible:
            return SeparateOutcome(query_id=query_id, reason=NO_SHARING_RULE_REASON)
        return query

    def plan(self, queries: Sequence[SharingQuery]) -> SharingPlan:
        return self._planner.plan(queries)

    def _run_group(self, executor: HogQLQueryExecutor, group: ExecutionGroup) -> dict[str, BatchQueryResult]:
        settings = executor.clickhouse_settings.model_copy() if executor.clickhouse_settings else None
        if settings is not None:
            settings.read_overflow_mode = "throw"
            settings.timeout_overflow_mode = "throw"
        query = clone_expr(group.query)
        row_cap = get_max_limit_for_context(executor.limit_context or LimitContext.QUERY)
        # Without its own LIMIT the shared query would get the default page size and drop rows a member needs.
        if isinstance(query, ast.SelectQuery) and query.limit is None:
            query.limit = ast.Constant(value=row_cap)
        shared = _CancellableExecutor(
            cancelled=self.cancelled,
            query=query,
            team=executor.team,
            user=executor.user,
            user_access_control=executor.context.user_access_control,
            modifiers=executor.query_modifiers,
            settings=settings,
            workload=executor.workload,
            ch_user=executor.ch_user,
            limit_context=executor.limit_context,
        ).execute()
        if (
            shared.error
            or shared.hasMore
            or shared.results is None
            or shared.types is None
            or len(shared.results) >= row_cap
        ):
            raise ValueError("Incomplete shared query result")
        return group.split(
            BatchQueryResult(
                columns=tuple(shared.columns or []),
                types=tuple(column[1] for column in shared.types),
                rows=tuple(tuple(row) for row in shared.results),
            )
        )

    def execute_group(self, executor: HogQLQueryExecutor, group: ExecutionGroup) -> dict[str, QueryOutcome]:
        """Run a group once. Every member is either shared, or falls back together if the shared result is unusable."""
        if self.cancelled.is_set():
            raise CancelledError()
        try:
            split = self._run_group(executor, group)
            if split.keys() != set(group.query_ids):
                raise ValueError("Missing shared query consumer result")
        except CancelledError:
            raise
        except Exception:
            return {
                query_id: FallbackOutcome(query_id=query_id, rule=group.rule, reason=SHARED_EXECUTION_FAILED_REASON)
                for query_id in group.query_ids
            }
        return {
            query_id: SharedOutcome(
                query_id=query_id,
                rule=group.rule,
                response=HogQLQueryResponse(
                    results=list(result.rows),
                    columns=list(result.columns),
                    types=list(zip(result.columns, result.types)),
                    hasMore=False,
                ),
            )
            for query_id, result in split.items()
        }
