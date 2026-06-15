from typing import Any, cast

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import LazyJoinToAdd
from posthog.hogql.database.utils import qualify_join_key_expr
from posthog.hogql.errors import ResolutionError


def _qualified_key_expr(table_key: str, table_name: str) -> ast.Expr:
    expr = qualify_join_key_expr(table_key, table_name)
    if expr is None:
        raise ResolutionError("Data Warehouse Join HogQL expression should be a Field or Call node")
    return expr


def resolve_foreign_key_join(join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery) -> ast.JoinExpr:
    lazy_join = join_to_add.lazy_join
    join_table = lazy_join.resolve_table(context)

    if isinstance(join_table.name, str):
        join_table_chain = cast(list[str | int], join_table.name.split("."))
    else:
        join_table_chain = [join_to_add.to_table]

    if not join_to_add.fields_accessed:
        raise ResolutionError(f"No fields requested from {join_to_add.to_table}")

    left = ast.Field(chain=[join_to_add.from_table, *lazy_join.from_field])
    right = ast.Field(chain=[join_to_add.to_table, *(lazy_join.to_field or [])])

    return ast.JoinExpr(
        table=ast.SelectQuery(
            select=[
                ast.Alias(alias=alias, expr=ast.Field(chain=chain))
                for alias, chain in join_to_add.fields_accessed.items()
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=join_table_chain)),
        ),
        join_type="LEFT JOIN",
        alias=join_to_add.to_table,
        constraint=ast.JoinConstraint(
            expr=ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=left, right=right),
            constraint_type="ON",
        ),
    )


def resolve_data_warehouse_join(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery
) -> ast.JoinExpr:
    params = join_to_add.lazy_join.resolver_params

    if not join_to_add.fields_accessed:
        raise ResolutionError(f"No fields requested from {join_to_add.to_table}")

    left = _qualified_key_expr(params["source_table_key"], join_to_add.from_table)
    right = _qualified_key_expr(params["joining_table_key"], join_to_add.to_table)

    return ast.JoinExpr(
        table=ast.SelectQuery(
            select=[
                ast.Alias(alias=alias, expr=ast.Field(chain=chain))
                for alias, chain in join_to_add.fields_accessed.items()
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=cast(list[str | int], str(params["joining_table_name"]).split(".")))
            ),
        ),
        join_type=params.get("join_type") or "LEFT JOIN",
        alias=join_to_add.to_table,
        constraint=ast.JoinConstraint(
            expr=ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=left, right=right),
            constraint_type="ON",
        ),
    )


def resolve_data_warehouse_experiments_join(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery
) -> ast.JoinExpr:
    params = join_to_add.lazy_join.resolver_params

    configuration = params.get("configuration")
    if not isinstance(configuration, dict):
        raise ResolutionError("experiments_optimized is not configured for this join")

    if params["joining_table_name"] != "events":
        raise ResolutionError("experiments_optimized is only supported for events table")

    if not configuration.get("experiments_optimized"):
        raise ResolutionError("experiments_optimized is not enabled for this join")

    timestamp_key = configuration.get("experiments_timestamp_key")
    if not isinstance(timestamp_key, str) or not timestamp_key:
        raise ResolutionError("experiments_timestamp_key is not set for this join")

    left = _qualified_key_expr(params["source_table_key"], join_to_add.from_table)
    right = _qualified_key_expr(params["joining_table_key"], join_to_add.to_table)

    where_exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value="$feature_flag_called"),
        )
    ]
    # :HACK: We need to pull the timestamp gt/lt values from node.where.exprs because
    # we can't reference the parent data warehouse table in the where clause.
    if node.where and hasattr(node.where, "exprs"):
        for expr in node.where.exprs:
            if isinstance(expr, ast.CompareOperation):
                if expr.op == ast.CompareOperationOp.GtEq or expr.op == ast.CompareOperationOp.LtEq:
                    # Match within hogql string because it could be 'toDateTime(timestamp)'
                    if isinstance(expr.left, ast.Alias) and timestamp_key in expr.left.expr.to_hogql():
                        where_exprs.append(
                            ast.CompareOperation(op=expr.op, left=ast.Field(chain=["timestamp"]), right=expr.right)
                        )

    return ast.JoinExpr(
        table=ast.SelectQuery(
            select=[
                ast.Alias(
                    alias=name,
                    expr=ast.Field(chain=["events", *(chain if isinstance(chain, list | tuple) else [chain])]),
                )
                for name, chain in {
                    **join_to_add.fields_accessed,
                    "event": ["event"],
                    "timestamp": ["timestamp"],
                    "distinct_id": ["distinct_id"],
                    "properties": ["properties"],
                }.items()
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=where_exprs),
        ),
        # ASOF JOIN finds the most recent matching event that occurred at or before each data warehouse timestamp.
        #
        # Why this matters:
        # When a user performs an action (recorded in data warehouse), we want to know which
        # experiment variant they were assigned at that moment. The most recent $feature_flag_called
        # event before their action represents their active variant assignment.
        #
        # Example:
        #   Data Warehouse: timestamp=2024-01-03 12:00, distinct_id=user1
        #   Events:
        #     2024-01-02: (user1, variant='control')   <- This event will be joined
        #     2024-01-03: (user1, variant='test')      <- Ignored (occurs after data warehouse timestamp)
        #
        # This ensures we capture the correct causal relationship: which experiment variant
        # was the user assigned to when they performed the action?
        join_type="ASOF LEFT JOIN",
        alias=join_to_add.to_table,
        constraint=ast.JoinConstraint(
            expr=ast.And(
                exprs=[
                    ast.CompareOperation(
                        left=ast.Field(chain=[join_to_add.to_table, "event"]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value="$feature_flag_called"),
                    ),
                    ast.CompareOperation(
                        left=left,
                        op=ast.CompareOperationOp.Eq,
                        right=right,
                    ),
                    ast.CompareOperation(
                        left=ast.Field(chain=[join_to_add.from_table, timestamp_key]),
                        op=ast.CompareOperationOp.GtEq,
                        right=ast.Field(chain=[join_to_add.to_table, "timestamp"]),
                    ),
                ]
            ),
            constraint_type="ON",
        ),
    )


def data_warehouse_resolver_params(
    *,
    source_table_key: str,
    joining_table_key: str,
    joining_table_name: str,
    configuration: dict | None = None,
    override_source_table_key: str | None = None,
    override_join_type: str | None = None,
) -> dict[str, Any]:
    """Build the serializable params the data-warehouse registry resolvers read back at resolution time."""
    return {
        "source_table_key": override_source_table_key or source_table_key,
        "joining_table_key": joining_table_key,
        "joining_table_name": joining_table_name,
        "join_type": override_join_type,
        "configuration": configuration if isinstance(configuration, dict) else {},
    }
