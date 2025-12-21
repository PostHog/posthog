from typing import Optional

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    FloatArrayDatabaseField,
    IntegerDatabaseField,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
)
from posthog.hogql.visitor import CloningVisitor

# Import the model table definitions
from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES

# Distance functions that can use vector similarity indexes
VECTOR_DISTANCE_FUNCTIONS = {"cosineDistance", "L2Distance", "L1Distance", "LinfDistance", "LpDistance"}

# Note: Using union view as fallback when model not specified
DOCUMENT_EMBEDDINGS_VIEW = "posthog_document_embeddings_union_view"

# Fields exposed by the embedding tables (excluding Kafka metadata)
DOCUMENT_EMBEDDINGS_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "product": StringDatabaseField(name="product", nullable=False),
    "document_type": StringDatabaseField(name="document_type", nullable=False),
    "model_name": StringDatabaseField(name="model_name", nullable=False),
    "rendering": StringDatabaseField(name="rendering", nullable=False),
    "document_id": StringDatabaseField(name="document_id", nullable=False),
    "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
    "inserted_at": DateTimeDatabaseField(name="inserted_at", nullable=False),
    "content": StringDatabaseField(name="content", nullable=False),
    "metadata": StringJSONDatabaseField(name="metadata", nullable=False),
    "embedding": FloatArrayDatabaseField(name="embedding", nullable=False),
}


def unwrap_alias(node):
    if isinstance(node, ast.Alias):
        return unwrap_alias(node.expr)
    return node


def get_field_val_pair(node) -> tuple[Optional[ast.Field], Optional[ast.Constant]]:
    left, right = None, None
    if isinstance(node, ast.CompareOperation) and node.op == ast.CompareOperationOp.Eq:
        left, right = unwrap_alias(node.left), unwrap_alias(node.right)
    elif isinstance(node, ast.Call) and node.name == "equals":
        if len(node.args) == 2:
            left, right = unwrap_alias(node.args[0]), unwrap_alias(node.args[1])

    # If left is value and right is field for some reason, swap them
    if isinstance(left, ast.Constant) and isinstance(right, ast.Field):
        left, right = right, left
    if not isinstance(left, ast.Field) or not isinstance(right, ast.Constant):
        return None, None
    return left, right


def is_vector_distance_call(expr: ast.Expr) -> bool:
    """Check if an expression is a vector distance function call involving the embedding field."""
    if isinstance(expr, ast.Alias):
        expr = expr.expr
    if isinstance(expr, ast.Call) and expr.name in VECTOR_DISTANCE_FUNCTIONS:
        # Check if any argument references the embedding field
        for arg in expr.args:
            # Unwrap Alias if present
            if isinstance(arg, ast.Alias):
                arg = arg.expr
            if isinstance(arg, ast.Field) and len(arg.chain) > 0:
                # Check if the last part of the chain is "embedding"
                if arg.chain[-1] == "embedding":
                    return True
    return False


def find_vector_distance_in_select(node: ast.SelectQuery) -> bool:
    """Check if the SELECT clause contains a vector distance function on embedding."""
    if not node.select:
        return False
    for select_expr in node.select:
        if is_vector_distance_call(select_expr):
            return True
    return False


def resolve_order_by_alias(order_expr: ast.OrderExpr, node: ast.SelectQuery) -> Optional[ast.Expr]:
    """If the ORDER BY references an alias in SELECT that is a distance function, return the function call."""
    expr = order_expr.expr

    if isinstance(expr, ast.Field) and len(expr.chain) == 1 and node.select:
        alias_name = expr.chain[0]
        for select_expr in node.select:
            if isinstance(select_expr, ast.Alias) and select_expr.alias == alias_name:
                if is_vector_distance_call(select_expr.expr):
                    return select_expr.expr
    return None


def is_vector_distance_order_by(order_expr: ast.OrderExpr, node: Optional[ast.SelectQuery] = None) -> bool:
    """Check if an ORDER BY expression involves a vector distance function on the embedding field.

    This handles two cases:
    1. Direct call: ORDER BY cosineDistance(embedding, ...)
    2. Alias reference: SELECT cosineDistance(embedding, ...) as dist ... ORDER BY dist
    """
    expr = order_expr.expr

    # Case 1: Direct call in ORDER BY
    if is_vector_distance_call(expr):
        return True

    # Case 2: Reference to an alias that is a distance function
    if node and resolve_order_by_alias(order_expr, node) is not None:
        return True

    return False


class FieldReferenceRewriter(CloningVisitor):
    """Rewrites field references to use the inner table name."""

    def __init__(self, outer_table_alias: str, inner_table_name: str):
        super().__init__(clear_locations=True)
        self.outer_table_alias = outer_table_alias
        self.inner_table_name = inner_table_name

    def visit_field(self, node: ast.Field):
        # If the field references the outer table alias (e.g., "document_embeddings.embedding"),
        # rewrite it to use the inner table name (e.g., "document_embeddings_text_embedding_3_large_3072.embedding")
        if len(node.chain) >= 2 and node.chain[0] == self.outer_table_alias:
            return ast.Field(chain=[self.inner_table_name, *node.chain[1:]])
        # If it's just a field name without table prefix, add the inner table prefix
        elif len(node.chain) == 1:
            return ast.Field(chain=[self.inner_table_name, node.chain[0]])
        return ast.Field(chain=list(node.chain))


# Gonna level with you homie this isn't the greatest code I've ever written
def extract_model_name_from_where(node):
    if not node:
        return None

    if isinstance(node, ast.And):
        for expr in node.exprs:
            result = extract_model_name_from_where(expr)
            if result:
                return result

    field, value = get_field_val_pair(node)
    if not field or not value:
        return None

    if len(field.chain) > 0 and field.chain[-1] == "model_name":
        return value.value

    return None


# Create a literal HogQL table for each model-specific distributed table
class ModelSpecificEmbeddingTable(Table):
    """A literal table reference to a model-specific distributed embeddings table."""

    model_name: str = ""
    clickhouse_table_name: str = ""

    def __init__(self, model_name: str, table_name: str):
        # Don't include model_name field since it's implicit from the table
        fields = {k: v for k, v in DOCUMENT_EMBEDDINGS_FIELDS.items() if k != "model_name"}
        # Initialize parent class with fields
        super().__init__(fields=fields)
        # Then set our custom attributes
        self.model_name = model_name
        self.clickhouse_table_name = table_name

    def to_printed_clickhouse(self, context: HogQLContext):
        return self.clickhouse_table_name

    def to_printed_hogql(self):
        return f"document_embeddings_{self.model_name.replace('-', '_')}"


# Create HogQL table instances for each model
HOGQL_EMBEDDING_TABLES = {
    table.model_name: ModelSpecificEmbeddingTable(
        model_name=table.model_name, table_name=table.distributed_table_name()
    )
    for table in EMBEDDING_TABLES
}

# Export for registration in database.py
# Dictionary with HogQL table names as keys for easy registration
HOGQL_MODEL_TABLES = {table.to_printed_hogql(): table for table in HOGQL_EMBEDDING_TABLES.values()}


class DocumentEmbeddingsTable(LazyTable):
    fields: dict[str, FieldOrTable] = DOCUMENT_EMBEDDINGS_FIELDS

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context: HogQLContext,
        node: ast.SelectQuery,
    ):
        from posthog.hogql import ast

        # Always include "document_id", as it's key to any further joins
        requested_fields = table_to_add.fields_accessed
        if "document_id" not in requested_fields:
            requested_fields = {**requested_fields, "document_id": ["document_id"]}

        # Try to extract model_name from WHERE clause
        model_name = extract_model_name_from_where(node.where if node else None)

        if model_name and model_name in HOGQL_EMBEDDING_TABLES:
            model_table = HOGQL_EMBEDDING_TABLES[model_name]
            table_name = model_table.to_printed_hogql()

            # Build select expressions
            exprs: list[ast.Expr] = []
            for name, chain in requested_fields.items():
                if name == "model_name":
                    # Add model_name as a constant since it's not in the model-specific table
                    exprs.append(ast.Alias(alias="model_name", expr=ast.Constant(value=model_table.model_name)))
                else:
                    exprs.append(ast.Alias(alias=name, expr=ast.Field(chain=[table_name, *chain])))

            # Check if we should push ORDER BY and LIMIT down for vector similarity index usage
            # ClickHouse vector similarity indexes only work when ORDER BY <distance_func>(...) LIMIT N
            # is directly on the table read, not on a subquery wrapper
            inner_order_by: list[ast.OrderExpr] | None = None
            inner_limit: ast.Expr | None = None

            if node and node.order_by and node.limit:
                # Check if any ORDER BY expression involves a vector distance function on embedding
                has_vector_order = any(is_vector_distance_order_by(order_expr, node) for order_expr in node.order_by)

                if has_vector_order:
                    # Rewrite field references in ORDER BY to use the inner table name
                    rewriter = FieldReferenceRewriter("document_embeddings", table_name)
                    inner_order_by = []
                    for order_expr in node.order_by:
                        # If this ORDER BY references an alias that is a distance function,
                        # replace the alias reference with the actual function call
                        resolved_expr = resolve_order_by_alias(order_expr, node)
                        if resolved_expr:
                            # Clone and rewrite the resolved expression
                            new_expr = rewriter.visit(resolved_expr)
                            inner_order_by.append(ast.OrderExpr(expr=new_expr, order=order_expr.order))
                        else:
                            # Just rewrite the existing expression
                            inner_order_by.append(rewriter.visit(order_expr))
                    # Push limit down to inner query
                    inner_limit = CloningVisitor(clear_locations=True).visit(node.limit)

            return ast.SelectQuery(
                select=exprs,
                select_from=ast.JoinExpr(
                    table=ast.Field(chain=[table_name]),
                ),
                order_by=inner_order_by,
                limit=inner_limit,
            )
        else:
            raise ValueError(f"Invalid model name: {model_name}")

    def to_printed_clickhouse(self, context: HogQLContext):
        raise NotImplementedError("LazyTables cannot be printed to ClickHouse SQL")

    def to_printed_hogql(self):
        return "document_embeddings"


# RawDocumentEmbeddingsTable as a direct reference to the union view
class RawDocumentEmbeddingsTable(Table):
    """Direct reference to the union view for backward compatibility."""

    fields: dict[str, FieldOrTable] = DOCUMENT_EMBEDDINGS_FIELDS

    def to_printed_clickhouse(self, context: HogQLContext):
        return DOCUMENT_EMBEDDINGS_VIEW

    def to_printed_hogql(self):
        return "raw_document_embeddings"
