from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    LazyJoinToAdd,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
)


class AiEventPropertiesTable(Table):
    fields: dict[str, FieldOrTable] = {
        "uuid": StringDatabaseField(name="uuid", nullable=False),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
        "ai_input": StringJSONDatabaseField(name="ai_input", nullable=False),
        "ai_output": StringJSONDatabaseField(name="ai_output", nullable=False),
        "ai_output_choices": StringJSONDatabaseField(name="ai_output_choices", nullable=False),
        "ai_input_state": StringJSONDatabaseField(name="ai_input_state", nullable=False),
        "ai_output_state": StringJSONDatabaseField(name="ai_output_state", nullable=False),
        "ai_tools": StringJSONDatabaseField(name="ai_tools", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "ai_event_properties"

    def to_printed_hogql(self):
        return "ai_event_properties"


def join_with_ai_event_properties_table(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: ast.SelectQuery,
) -> ast.JoinExpr:
    return ast.JoinExpr(
        alias=join_to_add.to_table,
        table=ast.Field(chain=["ai_event_properties"]),
        join_type="LEFT JOIN",
        constraint=ast.JoinConstraint(
            expr=ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=[join_to_add.from_table, "uuid"]),
                        right=ast.Field(chain=[join_to_add.to_table, "uuid"]),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=[join_to_add.from_table, "team_id"]),
                        right=ast.Field(chain=[join_to_add.to_table, "team_id"]),
                    ),
                ]
            ),
            constraint_type="ON",
        ),
    )
