from typing import Any, Dict

from django.db import models

from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import HogQLException
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UUIDModel

from .datawarehouse_saved_query import DataWarehouseSavedQuery


class DataWarehouseViewLink(CreatedMetaFields, UUIDModel, DeletedMetaFields):
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)
    table: models.CharField = models.CharField(max_length=128)
    from_join_key: models.CharField = models.CharField(max_length=400)
    saved_query: models.ForeignKey = models.ForeignKey(DataWarehouseSavedQuery, on_delete=models.CASCADE)
    to_join_key: models.CharField = models.CharField(max_length=400)

    @property
    def join_function(self):
        def _join_function(
            from_table: str,
            to_table: str,
            requested_fields: Dict[str, Any],
            context: HogQLContext,
            node: SelectQuery,
        ):
            from posthog.hogql import ast
            from posthog.hogql.parser import parse_select

            if not requested_fields:
                raise HogQLException(f"No fields requested from {to_table}")

            join_expr = ast.JoinExpr(
                table=parse_select(self.saved_query.query["query"]),
                join_type="INNER JOIN",
                alias=to_table,
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=[from_table, self.from_join_key]),
                        right=ast.Field(chain=[to_table, self.to_join_key]),
                    )
                ),
            )
            return join_expr

        return _join_function
