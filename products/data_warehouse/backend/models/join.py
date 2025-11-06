from datetime import datetime
from typing import Optional, cast
from warnings import warn

from django.db import models

from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import LazyJoinToAdd
from posthog.hogql.errors import ResolutionError
from posthog.hogql.parser import parse_expr

from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UUIDTModel

from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


class DataWarehouseViewLink(CreatedMetaFields, UUIDTModel, DeletedMetaFields):
    class Meta:
        db_table = "posthog_datawarehouseviewlink"

    """Deprecated model, use DataWarehouseJoin instead"""

    def __init_subclass__(cls, **kwargs):
        """This throws a deprecation warning on subclassing."""
        warn("DataWarehouseViewLink is deprecated, use DataWarehouseJoin", DeprecationWarning, stacklevel=2)
        super().__init_subclass__(**kwargs)

    def __init__(self, *args, **kwargs):
        """This throws a deprecation warning on initialization."""
        warn("DataWarehouseViewLink is deprecated, use DataWarehouseJoin", DeprecationWarning, stacklevel=2)
        super().__init__(*args, **kwargs)

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    table = models.CharField(max_length=128)
    from_join_key = models.CharField(max_length=400)
    saved_query = models.ForeignKey(DataWarehouseSavedQuery, on_delete=models.CASCADE)
    to_join_key = models.CharField(max_length=400)


class DataWarehouseJoin(CreatedMetaFields, UUIDTModel, DeletedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    source_table_name = models.CharField(max_length=400)
    source_table_key = models.CharField(max_length=400)
    joining_table_name = models.CharField(max_length=400)
    joining_table_key = models.CharField(max_length=400)
    field_name = models.CharField(max_length=400)
    configuration = models.JSONField(default=dict, null=True)

    class Meta:
        db_table = "posthog_datawarehousejoin"

    @property
    def joining_table_name_chain(self) -> list[str | int]:
        return cast(list[str | int], self.joining_table_name.split("."))

    def soft_delete(self):
        self.deleted = True
        self.deleted_at = datetime.now()
        self.save()

    def join_function(
        self,
        override_source_table_key: Optional[str] = None,
        override_joining_table_key: Optional[str] = None,
        override_join_type: Optional[str] = None,
    ):
        def _join_function(
            join_to_add: LazyJoinToAdd,
            context: HogQLContext,
            node: SelectQuery,
        ):
            _source_table_key = override_source_table_key or self.source_table_key
            _joining_table_key = override_joining_table_key or self.joining_table_key

            from posthog.hogql import ast

            if not join_to_add.fields_accessed:
                raise ResolutionError(f"No fields requested from {join_to_add.to_table}")

            left = self.parse_table_key_expression(_source_table_key, join_to_add.from_table)
            right = self.parse_table_key_expression(_joining_table_key, join_to_add.to_table)

            join_expr = ast.JoinExpr(
                table=ast.SelectQuery(
                    select=[
                        ast.Alias(alias=alias, expr=ast.Field(chain=chain))
                        for alias, chain in join_to_add.fields_accessed.items()
                    ],
                    select_from=ast.JoinExpr(table=ast.Field(chain=self.joining_table_name_chain)),
                ),
                join_type=override_join_type or "LEFT JOIN",
                alias=join_to_add.to_table,
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=left,
                        right=right,
                    ),
                    constraint_type="ON",
                ),
            )
            return join_expr

        return _join_function

    def join_function_for_experiments(self):
        def _join_function_for_experiments(
            join_to_add: LazyJoinToAdd,
            context: HogQLContext,
            node: SelectQuery,
        ):
            if self.joining_table_name != "events":
                raise ResolutionError("experiments_optimized is only supported for events table")

            if not self.configuration.get("experiments_optimized"):
                raise ResolutionError("experiments_optimized is not enabled for this join")

            timestamp_key = self.configuration.get("experiments_timestamp_key")
            if not timestamp_key:
                raise ResolutionError("experiments_timestamp_key is not set for this join")

            left = self.parse_table_key_expression(self.source_table_key, join_to_add.from_table)
            right = self.parse_table_key_expression(self.joining_table_key, join_to_add.to_table)

            whereExpr: list[ast.Expr] = [
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["event"]),
                    right=ast.Constant(value="$feature_flag_called"),
                )
            ]
            # :HACK: We need to pull the timestamp gt/lt values from node.where.exprs[0] because
            # we can't reference the parent data warehouse table in the where clause.
            if node.where and hasattr(node.where, "exprs"):
                for expr in node.where.exprs:
                    if isinstance(expr, ast.CompareOperation):
                        if expr.op == ast.CompareOperationOp.GtEq or expr.op == ast.CompareOperationOp.LtEq:
                            # Match within hogql string because it could be 'toDateTime(timestamp)'
                            if isinstance(expr.left, ast.Alias) and timestamp_key in expr.left.expr.to_hogql():
                                whereExpr.append(
                                    ast.CompareOperation(
                                        op=expr.op, left=ast.Field(chain=["timestamp"]), right=expr.right
                                    )
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
                    where=ast.And(exprs=whereExpr),
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
                                left=ast.Field(
                                    chain=[
                                        join_to_add.from_table,
                                        timestamp_key,
                                    ]
                                ),
                                op=ast.CompareOperationOp.GtEq,
                                right=ast.Field(chain=[join_to_add.to_table, "timestamp"]),
                            ),
                        ]
                    ),
                    constraint_type="ON",
                ),
            )

        return _join_function_for_experiments

    @classmethod
    def parse_table_key_expression(cls, table_key: str, table_name: str) -> ast.Expr:
        expr = parse_expr(table_key)
        if isinstance(expr, ast.Field):
            expr.chain = [table_name, *expr.chain]
        elif isinstance(expr, ast.Call) and isinstance(expr.args[0], ast.Field):
            expr.args[0].chain = [table_name, *expr.args[0].chain]
        elif (
            isinstance(expr, ast.Alias) and isinstance(expr.expr, ast.Call) and isinstance(expr.expr.args[0], ast.Field)
        ):
            expr.expr.args[0].chain = [table_name, *expr.expr.args[0].chain]
        else:
            raise ResolutionError("Data Warehouse Join HogQL expression should be a Field or Call node")

        return expr
