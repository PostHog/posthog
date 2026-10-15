from collections.abc import Iterator, Sequence
from dataclasses import fields

from posthog.hogql import ast
from posthog.hogql.batch import BatchQueryResult, CountBatchPlanner
from posthog.hogql.multi_query import ExecutionGroup, RuleProposals, RuleRejection, SharingQuery
from posthog.hogql.visitor import clone_expr

from posthog.dataclasses import frozen


class CountFusionRule:
    name = "count_fusion"

    def propose(self, queries: Sequence[SharingQuery]) -> RuleProposals:
        plan = CountBatchPlanner(max_group_size=2).plan({q.query_id: q.query for q in queries})
        return RuleProposals(
            groups=tuple(
                ExecutionGroup(query_ids=s.query_ids, query=s.query, rule=self.name, router=s)
                for s in plan.steps
                if len(s.query_ids) > 1
            ),
            rejections=tuple(
                RuleRejection(query_id=s.query_ids[0], rule=self.name, reason=s.reason)
                for s in plan.steps
                if len(s.query_ids) == 1
            ),
        )


def _nodes(value: object) -> Iterator[ast.AST]:
    if isinstance(value, ast.AST):
        yield value
        for member in fields(value):
            if member.name not in ("type", "start", "end"):
                yield from _nodes(getattr(value, member.name))
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _nodes(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _nodes(item)


@frozen
class _TopNQuery:
    query_id: str
    body: ast.SelectQuery
    columns: tuple[str, ...]
    output_columns: tuple[str, ...]
    ordering: tuple[ast.OrderExpr, ...]
    limit: int


@frozen
class TopNResultRouter:
    query_ids: tuple[str, ...]
    columns: tuple[str, ...]
    limits: tuple[int, ...]

    def split(self, result: BatchQueryResult) -> dict[str, BatchQueryResult]:
        width = len(self.columns)
        if len(result.columns) != width + 2 or len(result.types) != width + 2:
            raise ValueError("Unexpected shared top-N result schema")
        rows: list[list[tuple[object, ...]]] = [[] for _ in self.query_ids]
        for row in result.rows:
            if len(row) != width + 2:
                raise ValueError("Unexpected shared top-N row width")
            consumer, rank = row[-2:]
            if type(consumer) is not int or not 0 <= consumer < len(rows):
                raise ValueError("Invalid shared top-N consumer")
            if type(rank) is not int or rank != len(rows[consumer]) + 1 or rank > self.limits[consumer]:
                raise ValueError("Invalid shared top-N rank")
            rows[consumer].append(row[:width])
        return {
            query_id: BatchQueryResult(columns=self.columns, types=result.types[:width], rows=tuple(rows[index]))
            for index, query_id in enumerate(self.query_ids)
        }


class SameAggregationTopNRule:
    name = "same_aggregation_top_n"
    prefix = "__sharing_"
    aggregates = frozenset({"count", "uniq", "uniqExact", "min", "max", "sum"})
    scalar_functions = frozenset(
        {"toDate", "toDateTime", "toString", "if", "ifNull", "coalesce", "isNull", "isNotNull"}
    )

    @classmethod
    def _candidate(cls, query: SharingQuery) -> _TopNQuery | str:
        node = query.query
        if not isinstance(node, ast.SelectQuery):
            return "set operations are not supported"
        if (
            not isinstance(node.limit, ast.Constant)
            or type(node.limit.value) is not int
            or not 1 <= node.limit.value <= 1000
        ):
            return "requires an explicit LIMIT between 1 and 1000"
        if not node.group_by or not node.order_by:
            return "requires grouping and explicit ordering"
        supported = {"select", "select_from", "where", "prewhere", "group_by", "having", "order_by", "limit"}
        for member in fields(node):
            if member.name not in supported | {"type", "start", "end"} and getattr(node, member.name) is not None:
                return f"unsupported SELECT option: {member.name}"
        columns: list[str] = []
        for selected in node.select:
            if isinstance(selected, ast.Alias):
                columns.append(selected.alias)
            elif (
                isinstance(selected, ast.Field)
                and len(selected.chain) == 1
                and isinstance(selected.chain[0], str)
                and selected.chain[0] != "*"
            ):
                columns.append(selected.chain[0])
            else:
                return "selected expressions require explicit aliases"
        if len(set(columns)) != len(columns):
            return "duplicate output names"
        output_ordering: list[ast.OrderExpr] = []
        expressions = [selected.expr if isinstance(selected, ast.Alias) else selected for selected in node.select]
        for ordering in node.order_by:
            if isinstance(ordering.expr, ast.Constant):
                return "positional or constant ordering is not supported"
            if ordering.with_fill:
                return "ordering must reference output columns without WITH FILL"
            if isinstance(ordering.expr, ast.Field) and ordering.expr.chain in [[c] for c in columns]:
                output_ordering.append(clone_expr(ordering))
            elif ordering.expr in expressions:
                output_ordering.append(
                    ast.OrderExpr(
                        expr=ast.Field(chain=[columns[expressions.index(ordering.expr)]]), order=ordering.order
                    )
                )
            else:
                return "ordering must reference output columns without WITH FILL"
        source_queries: set[int] = {id(node)}
        source_query = node
        while source_query.select_from and isinstance(source_query.select_from.table, ast.SelectQuery):
            source_query = source_query.select_from.table
            source_queries.add(id(source_query))
            if any(
                getattr(source_query, member.name) is not None
                for member in fields(source_query)
                if member.name
                not in {"select", "select_from", "where", "prewhere", "view_name", "type", "start", "end"}
            ):
                return "nested inputs must be deterministic projections and filters"
        found_aggregate = False
        for child in _nodes(node):
            if isinstance(child, ast.Field) and any(
                isinstance(p, str) and p.startswith(cls.prefix) for p in child.chain
            ):
                return "reserved sharing identifier"
            if isinstance(child, ast.Alias) and child.alias.startswith(cls.prefix):
                return "reserved sharing identifier"
            if isinstance(child, ast.Call):
                if child.name not in cls.aggregates | cls.scalar_functions:
                    return f"unsupported or potentially volatile function: {child.name}"
                if child != ast.Call(name=child.name, args=child.args):
                    return "aggregate modifiers and parameters are not supported"
                found_aggregate |= child.name in cls.aggregates
            elif isinstance(child, ast.JoinExpr):
                if child != ast.JoinExpr(table=child.table, alias=child.alias):
                    return "joins, sampling and table functions are not supported"
                if child.alias and child.alias.startswith(cls.prefix):
                    return "reserved sharing identifier"
                if not isinstance(child.table, ast.SelectQuery) and not (
                    # This syntax-only rule leaves qualified and unresolved sources separate.
                    # nosemgrep: hogql-no-string-table-chain
                    isinstance(child.table, ast.Field) and child.table.chain == ["events"]
                ):
                    return "only events or expanded deterministic events projections are supported"
            elif isinstance(child, ast.SelectQuery):
                if id(child) not in source_queries:
                    return "predicate subqueries are not supported"
            elif not isinstance(
                child,
                (
                    ast.SelectQuery,
                    ast.Alias,
                    ast.Field,
                    ast.Constant,
                    ast.OrderExpr,
                    ast.CompareOperation,
                    ast.And,
                    ast.Or,
                    ast.Not,
                    ast.Tuple,
                    ast.Array,
                ),
            ):
                return f"unsupported expression: {type(child).__name__}"
        if not node.select_from or not found_aggregate:
            return "requires an events aggregation"
        body = clone_expr(node)
        body.order_by = None
        body.limit = None
        return _TopNQuery(
            query_id=query.query_id,
            body=body,
            columns=tuple(columns),
            output_columns=query.output_columns or tuple(columns),
            ordering=tuple(output_ordering),
            limit=node.limit.value,
        )

    @classmethod
    def _combine(cls, queries: tuple[_TopNQuery, _TopNQuery]) -> ExecutionGroup:
        first = queries[0]
        projected = [ast.Field(chain=[column]) for column in first.columns]
        ranked = ast.SelectQuery(
            select=[
                *projected,
                *[
                    ast.Alias(
                        alias=f"{cls.prefix}rank_{i}",
                        expr=ast.WindowFunction(
                            name="row_number",
                            args=[],
                            over_expr=ast.WindowExpr(order_by=[clone_expr(o) for o in q.ordering]),
                        ),
                    )
                    for i, q in enumerate(queries)
                ],
            ],
            select_from=ast.JoinExpr(table=clone_expr(first.body), alias=f"{cls.prefix}aggregate"),
        )
        consumer = ast.Field(chain=[f"{cls.prefix}consumer"])
        ranks = [ast.Field(chain=[f"{cls.prefix}rank_{i}"]) for i in range(2)]
        selected_rank = ast.Call(
            name="if",
            args=[
                ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=consumer, right=ast.Constant(value=0)),
                ranks[0],
                ranks[1],
            ],
        )
        selected_limit = ast.Call(
            name="if",
            args=[
                ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=consumer, right=ast.Constant(value=0)),
                ast.Constant(value=queries[0].limit),
                ast.Constant(value=queries[1].limit),
            ],
        )
        output = ast.SelectQuery(
            select=[
                *[clone_expr(p) for p in projected],
                consumer,
                ast.Alias(alias=f"{cls.prefix}rank", expr=selected_rank),
            ],
            select_from=ast.JoinExpr(table=ranked, alias=f"{cls.prefix}ranked"),
            array_join_op="ARRAY JOIN",
            array_join_list=[
                ast.Alias(
                    alias=f"{cls.prefix}consumer", expr=ast.Array(exprs=[ast.Constant(value=0), ast.Constant(value=1)])
                )
            ],
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq, left=clone_expr(selected_rank), right=selected_limit
            ),
            order_by=[
                ast.OrderExpr(expr=clone_expr(consumer)),
                ast.OrderExpr(expr=ast.Field(chain=[f"{cls.prefix}rank"])),
            ],
            limit=ast.Constant(value=sum(q.limit for q in queries)),
        )
        return ExecutionGroup(
            query_ids=tuple(q.query_id for q in queries),
            query=output,
            rule=cls.name,
            router=TopNResultRouter(
                query_ids=tuple(q.query_id for q in queries),
                columns=first.output_columns,
                limits=tuple(q.limit for q in queries),
            ),
        )

    def propose(self, queries: Sequence[SharingQuery]) -> RuleProposals:
        buckets: dict[str, list[_TopNQuery]] = {}
        rejections: list[RuleRejection] = []
        for query in queries:
            candidate = self._candidate(query)
            if isinstance(candidate, str):
                rejections.append(RuleRejection(query_id=query.query_id, rule=self.name, reason=candidate))
            else:
                buckets.setdefault(repr((candidate.body, candidate.output_columns)), []).append(candidate)
        groups: list[ExecutionGroup] = []
        for bucket in buckets.values():
            for i in range(0, len(bucket) - 1, 2):
                groups.append(self._combine((bucket[i], bucket[i + 1])))
            if len(bucket) % 2:
                rejections.append(
                    RuleRejection(
                        query_id=bucket[-1].query_id, rule=self.name, reason="no identical aggregation partner"
                    )
                )
        return RuleProposals(groups=tuple(groups), rejections=tuple(rejections))
