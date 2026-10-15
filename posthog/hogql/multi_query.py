from collections.abc import Callable, Sequence
from dataclasses import field, replace
from typing import TYPE_CHECKING, Protocol

import posthoganalytics

from posthog.hogql import ast
from posthog.hogql.batch import BatchQueryResult
from posthog.hogql.visitor import CloningVisitor, clone_expr

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models.team import Team

QUERY_SHARING_FLAG = "hogql-query-sharing"


def is_query_sharing_enabled(team: "Team") -> bool:
    try:
        return (
            posthoganalytics.feature_enabled(
                QUERY_SHARING_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.pk)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.pk)},
                },
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
            is True
        )
    except Exception:
        return False


@frozen
class SharingQuery:
    query_id: str
    query: ast.SelectQuery | ast.SelectSetQuery
    # Equality must include the caller's authorization, schema, settings and time context.
    context_key: str = field(repr=False)
    output_columns: tuple[str, ...] | None = None
    sharing_enabled: bool = False


class ResultRouter(Protocol):
    def split(self, result: BatchQueryResult) -> dict[str, BatchQueryResult]: ...


@frozen
class SingleResultRouter:
    query_id: str

    def split(self, result: BatchQueryResult) -> dict[str, BatchQueryResult]:
        return {self.query_id: result}


@frozen
class ExecutionGroup:
    query_ids: tuple[str, ...]
    query: ast.SelectQuery | ast.SelectSetQuery
    rule: str
    router: ResultRouter

    def split(self, result: BatchQueryResult) -> dict[str, BatchQueryResult]:
        return self.router.split(result)


@frozen
class RuleRejection:
    query_id: str
    rule: str
    reason: str


@frozen
class RuleProposals:
    groups: tuple[ExecutionGroup, ...]
    rejections: tuple[RuleRejection, ...] = ()


class SharingRule(Protocol):
    name: str

    def propose(self, queries: Sequence[SharingQuery]) -> RuleProposals: ...


@frozen
class SharingPlan:
    groups: tuple[ExecutionGroup, ...]
    rejections: tuple[RuleRejection, ...]


class _UnwrapHiddenAliases(CloningVisitor):
    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        # Resolver-inserted aliases describe bindings rather than user-defined SQL aliases.
        if node.hidden:
            return self.visit(node.expr)
        return super().visit_alias(node)


class MultiQueryPlanner:
    """Plan within caller-validated contexts; this class does not authorize or execute queries."""

    def __init__(self, rules: Sequence[SharingRule], *, max_queries: int = 32) -> None:
        if not 1 <= max_queries <= 256:
            raise ValueError("max_queries must be between 1 and 256")
        self.rules = tuple(rules)
        self.max_queries = max_queries

    def plan(self, queries: Sequence[SharingQuery], *, combine: bool = True) -> SharingPlan:
        if len(queries) > self.max_queries:
            raise ValueError("Query count exceeds the planning limit")
        if len({query.query_id for query in queries}) != len(queries):
            raise ValueError("Query IDs must be unique")
        remaining = {
            q.query_id: replace(
                q,
                query=_UnwrapHiddenAliases().visit(clone_expr(q.query, clear_types=True, clear_locations=True)),
            )
            for q in queries
        }
        groups: list[ExecutionGroup] = []
        rejections = [
            RuleRejection(query_id=q.query_id, rule="feature_flag", reason="HogQL query sharing is disabled")
            for q in queries
            if combine and not q.sharing_enabled
        ]
        for rule in self.rules if combine else ():
            contexts: dict[str, list[SharingQuery]] = {}
            for query in remaining.values():
                if query.sharing_enabled:
                    contexts.setdefault(query.context_key, []).append(query)
            for candidates in contexts.values():
                proposals = rule.propose(candidates)
                rejections.extend(proposals.rejections)
                allowed = {query.query_id for query in candidates}
                for group in proposals.groups:
                    if (
                        len(group.query_ids) < 2
                        or len(set(group.query_ids)) != len(group.query_ids)
                        or not set(group.query_ids) <= allowed
                        or not set(group.query_ids) <= remaining.keys()
                    ):
                        raise ValueError(f"Invalid or overlapping proposal from {rule.name}")
                    groups.append(group)
                    for query_id in group.query_ids:
                        del remaining[query_id]
        groups.extend(
            ExecutionGroup(
                query_ids=(q.query_id,),
                query=q.query,
                rule="separate",
                router=SingleResultRouter(query_id=q.query_id),
            )
            for q in remaining.values()
        )
        positions = {q.query_id: index for index, q in enumerate(queries)}
        groups.sort(key=lambda group: min(positions[q] for q in group.query_ids))
        return SharingPlan(groups=tuple(groups), rejections=tuple(rejections))


def execute_group(
    group: ExecutionGroup, run_query: Callable[[ast.SelectQuery | ast.SelectSetQuery], BatchQueryResult]
) -> dict[str, BatchQueryResult]:
    result = group.split(run_query(clone_expr(group.query)))
    if set(result) != set(group.query_ids):
        raise ValueError("Result router did not return exactly the group's consumers")
    return result
