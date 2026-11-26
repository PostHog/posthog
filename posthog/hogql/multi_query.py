from collections.abc import Callable, Iterator, Sequence
from dataclasses import field, fields, replace
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
    default_limit: int | None = None


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


def ast_nodes(value: object) -> Iterator[ast.AST]:
    if isinstance(value, ast.AST):
        yield value
        for member in fields(value):
            if member.name not in ("type", "start", "end"):
                yield from ast_nodes(getattr(value, member.name))
    elif isinstance(value, list | tuple):
        for item in value:
            yield from ast_nodes(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from ast_nodes(item)


class _UnqualifyTableAlias(CloningVisitor):
    def __init__(self, table_alias: str) -> None:
        super().__init__(clear_types=True, clear_locations=True)
        self.table_alias = table_alias

    def visit_field(self, node: ast.Field) -> ast.Field:
        field = super().visit_field(node)
        if len(field.chain) > 1 and field.chain[0] == self.table_alias:
            field.chain = field.chain[1:]
        return field


def _select_aliases(query: ast.SelectQuery) -> dict[str, ast.Expr] | None:
    aliases: dict[str, ast.Expr] = {}
    for selected in query.select:
        if isinstance(selected, ast.Alias):
            if selected.alias in aliases:
                return None
            aliases[selected.alias] = selected.expr
    return aliases


def _without_table_alias(query: ast.SelectQuery, output_columns: tuple[str, ...] | None) -> ast.SelectQuery:
    """Read `FROM events AS e` and `e.event` as `FROM events` and `event`, or return the query unchanged.

    The rewrite is only exact when nothing can rebind a name: a subquery or lambda could declare its own `e` or
    `event`, and a SELECT alias named like the table alias or like an unqualified column would capture the field.
    """
    source = query.select_from
    if source is None or source.alias is None:
        return query
    # This syntax-only rewrite leaves qualified and unresolved sources alone.
    # nosemgrep: hogql-no-string-table-chain
    if source != ast.JoinExpr(table=ast.Field(chain=["events"]), alias=source.alias):
        return query
    table_alias = source.alias
    aliases = _select_aliases(query)
    if aliases is None or table_alias in aliases:
        return query
    if output_columns is not None and len(output_columns) != len(query.select):
        return query
    field_names: set[str] = set()
    for node in ast_nodes(query):
        if node is not query and isinstance(node, ast.SelectQuery | ast.SelectSetQuery | ast.Lambda):
            return query
        if isinstance(node, ast.Field) and node.chain and node is not source.table:
            if node.chain[0] == table_alias:
                if len(node.chain) < 2 or node.chain[1] in aliases:
                    return query
                field_names.add(str(node.chain[1]))
            else:
                field_names.add(str(node.chain[0]))
    rewritten = _UnqualifyTableAlias(table_alias).visit(query)
    # nosemgrep: hogql-no-string-table-chain
    rewritten.select_from = ast.JoinExpr(table=ast.Field(chain=["events"]))
    # An unaliased expression takes its output name from its text, so keep the name the original text produced.
    for index, (before, after) in enumerate(zip(query.select, rewritten.select)):
        if isinstance(before, ast.Alias) or before == after:
            continue
        # The resolver, not the syntax printer, determines output names (especially for fields).
        if output_columns is None:
            return query
        name = output_columns[index]
        if isinstance(after, ast.Field) and after.chain == [name]:
            continue
        if name in aliases or name in field_names:
            return query
        rewritten.select[index] = ast.Alias(alias=name, expr=after)
    return rewritten


def _with_resolved_group_by(query: ast.SelectQuery) -> ast.SelectQuery:
    """Replace each GROUP BY entry that names a SELECT alias with the aliased expression.

    HogQL resolves an unqualified name to a SELECT alias before a column, so `GROUP BY day` groups by the aliased
    expression. An expression that itself names a SELECT alias would bind differently once copied, so it stays.
    """
    aliases = _select_aliases(query)
    if not query.group_by or not aliases:
        return query
    group_by: list[ast.Expr] = []
    for entry in query.group_by:
        expr = (
            aliases.get(entry.chain[0])
            if isinstance(entry, ast.Field) and len(entry.chain) == 1 and isinstance(entry.chain[0], str)
            else None
        )
        if expr is None or any(
            isinstance(node, ast.Field) and node.chain and node.chain[0] in aliases for node in ast_nodes(expr)
        ):
            group_by.append(entry)
        else:
            group_by.append(clone_expr(expr))
    return replace(query, group_by=group_by)


def normalise_for_sharing(
    query: ast.SelectQuery | ast.SelectSetQuery, output_columns: tuple[str, ...] | None
) -> ast.SelectQuery | ast.SelectSetQuery:
    """Rewrite spellings of the same top-level query to one form, so sharing rules can match them.

    The result returns the same rows under the same output names as the input.
    """
    if not isinstance(query, ast.SelectQuery):
        return query
    return _with_resolved_group_by(_without_table_alias(query, output_columns))


@frozen
class _DefaultLimitRouter:
    inner: ResultRouter
    limits: dict[str, int] = field(hash=False)

    def split(self, result: BatchQueryResult) -> dict[str, BatchQueryResult]:
        split = self.inner.split(result)
        return {
            query_id: replace(rows, rows=rows.rows[: self.limits[query_id]]) if query_id in self.limits else rows
            for query_id, rows in split.items()
        }


def _with_default_limit(query: SharingQuery) -> ast.SelectQuery | ast.SelectSetQuery:
    if query.default_limit is None or not isinstance(query.query, ast.SelectQuery) or query.query.limit is not None:
        return query.query
    return replace(query.query, limit=ast.Constant(value=query.default_limit))


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
        # Queries that no rule shares run as written. Only the rules see the normalised form.
        originals = {
            q.query_id: _UnwrapHiddenAliases().visit(clone_expr(q.query, clear_types=True, clear_locations=True))
            for q in queries
        }
        remaining = {
            q.query_id: replace(q, query=normalise_for_sharing(clone_expr(originals[q.query_id]), q.output_columns))
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
                    limits: dict[str, int] = {}
                    for query_id in group.query_ids:
                        default_limit = remaining[query_id].default_limit
                        if default_limit is not None:
                            limits[query_id] = default_limit
                    if limits:
                        group = replace(group, router=_DefaultLimitRouter(inner=group.router, limits=limits))
                    groups.append(group)
                    for query_id in group.query_ids:
                        del remaining[query_id]
        groups.extend(
            ExecutionGroup(
                query_ids=(q.query_id,),
                query=_with_default_limit(replace(q, query=originals[q.query_id])),
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
