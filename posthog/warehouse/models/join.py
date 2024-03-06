from typing import Any, Dict, List
from warnings import warn

from django.db import models

from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import HogQLException
from posthog.hogql.parser import parse_expr
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UUIDModel
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery


class DataWarehouseViewLink(CreatedMetaFields, UUIDModel, DeletedMetaFields):
    """Deprecated model, use DataWarehouseJoin instead"""

    def __init_subclass__(cls, **kwargs):
        """This throws a deprecation warning on subclassing."""
        warn("DataWarehouseViewLink is deprecated, use DataWarehouseJoin", DeprecationWarning, stacklevel=2)
        super().__init_subclass__(**kwargs)

    def __init__(self, *args, **kwargs):
        """This throws a deprecation warning on initialization."""
        warn("DataWarehouseViewLink is deprecated, use DataWarehouseJoin", DeprecationWarning, stacklevel=2)
        super().__init__(*args, **kwargs)

    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    table: models.CharField = models.CharField(max_length=128)
    from_join_key: models.CharField = models.CharField(max_length=400)
    saved_query: models.ForeignKey = models.ForeignKey(DataWarehouseSavedQuery, on_delete=models.CASCADE)
    to_join_key: models.CharField = models.CharField(max_length=400)


class DataWarehouseJoin(CreatedMetaFields, UUIDModel, DeletedMetaFields):
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    source_table_name: models.CharField = models.CharField(max_length=400)
    source_table_key: models.CharField = models.CharField(max_length=400)
    source_table_key_hogql: models.CharField = models.CharField(max_length=400, null=True)
    joining_table_name: models.CharField = models.CharField(max_length=400)
    joining_table_key: models.CharField = models.CharField(max_length=400)
    joining_table_key_hogql: models.CharField = models.CharField(max_length=400, null=True)
    field_name: models.CharField = models.CharField(max_length=400)

    @property
    def join_function(self):
        def _join_function(
            from_table: str,
            to_table: str,
            requested_fields: Dict[str, Any],
            join_constraint_overrides: Dict[str, List[str | int]],
            context: HogQLContext,
            node: SelectQuery,
        ):
            from posthog.hogql import ast

            if not requested_fields:
                raise HogQLException(f"No fields requested from {to_table}")

            if self.source_table_key == "$hogql":
                left = parse_expr(self.source_table_key_hogql)
                if not isinstance(left, ast.Field):
                    raise HogQLException("Data Warehouse Join HogQL expression should be a Field node")
                left.chain = [from_table, *left.chain]
            else:
                left = ast.Field(chain=[from_table, self.source_table_key])

            if self.joining_table_key == "$hogql":
                right = parse_expr(self.joining_table_key_hogql)
                if not isinstance(right, ast.Field):
                    raise HogQLException("Data Warehouse Join HogQL expression should be a Field node")
                right.chain = [to_table, *right.chain]
            else:
                right = ast.Field(chain=[to_table, self.joining_table_key])

            for new_alias, chain in join_constraint_overrides.items():
                if left.chain == chain:
                    left.chain = [from_table, new_alias]

                if right.chain == chain:
                    right.chain = [to_table, new_alias]

            join_expr = ast.JoinExpr(
                table=ast.Field(chain=[self.joining_table_name]),
                join_type="LEFT JOIN",
                alias=to_table,
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=left,
                        right=right,
                    )
                ),
            )
            return join_expr

        return _join_function
