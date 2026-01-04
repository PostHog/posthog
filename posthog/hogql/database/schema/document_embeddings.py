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

from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES

VECTOR_DISTANCE_FUNCTIONS = {"cosineDistance", "L2Distance"}
DOCUMENT_EMBEDDINGS_VIEW = "posthog_document_embeddings_union_view"

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

    if isinstance(left, ast.Constant) and isinstance(right, ast.Field):
        left, right = right, left
    if not isinstance(left, ast.Field) or not isinstance(right, ast.Constant):
        return None, None
    return left, right


def is_vector_distance_call(expr: ast.Expr) -> bool:
    expr = unwrap_alias(expr)
    if not isinstance(expr, ast.Call) or expr.name not in VECTOR_DISTANCE_FUNCTIONS:
        return False
    return any(
        isinstance(unwrap_alias(arg), ast.Field) and unwrap_alias(arg).chain[-1] == "embedding" for arg in expr.args
    )


def resolve_order_by_alias(order_expr: ast.OrderExpr, node: ast.SelectQuery) -> Optional[ast.Expr]:
    expr = unwrap_alias(order_expr.expr)
    if not isinstance(expr, ast.Field) or len(expr.chain) != 1 or not node.select:
        return None
    alias_name = expr.chain[0]
    for select_expr in node.select:
        if isinstance(select_expr, ast.Alias) and select_expr.alias == alias_name:
            if is_vector_distance_call(select_expr.expr):
                return select_expr.expr
    return None


def is_vector_distance_order_by(order_expr: ast.OrderExpr, node: Optional[ast.SelectQuery] = None) -> bool:
    if is_vector_distance_call(order_expr.expr):
        return True
    return node is not None and resolve_order_by_alias(order_expr, node) is not None


class FieldReferenceRewriter(CloningVisitor):
    def __init__(self, outer_table_alias: str, inner_table_name: str):
        super().__init__(clear_locations=True)
        self.outer_table_alias = outer_table_alias
        self.inner_table_name = inner_table_name

    def visit_field(self, node: ast.Field):
        if len(node.chain) >= 2 and node.chain[0] == self.outer_table_alias:
            return ast.Field(chain=[self.inner_table_name, *node.chain[1:]])
        elif len(node.chain) == 1:
            return ast.Field(chain=[self.inner_table_name, node.chain[0]])
        return ast.Field(chain=list(node.chain))


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


class ModelSpecificEmbeddingTable(Table):
    model_name: str = ""
    clickhouse_table_name: str = ""

    def __init__(self, model_name: str, table_name: str):
        fields = {k: v for k, v in DOCUMENT_EMBEDDINGS_FIELDS.items() if k != "model_name"}
        super().__init__(fields=fields)
        self.model_name = model_name
        self.clickhouse_table_name = table_name

    def to_printed_clickhouse(self, context: HogQLContext):
        return self.clickhouse_table_name

    def to_printed_hogql(self):
        return f"document_embeddings_{self.model_name.replace('-', '_')}"


HOGQL_EMBEDDING_TABLES = {
    table.model_name: ModelSpecificEmbeddingTable(
        model_name=table.model_name, table_name=table.distributed_table_name()
    )
    for table in EMBEDDING_TABLES
}

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

        requested_fields = table_to_add.fields_accessed
        if "document_id" not in requested_fields:
            requested_fields = {**requested_fields, "document_id": ["document_id"]}

        model_name = extract_model_name_from_where(node.where if node else None)

        if model_name and model_name in HOGQL_EMBEDDING_TABLES:
            model_table = HOGQL_EMBEDDING_TABLES[model_name]
            table_name = model_table.to_printed_hogql()

            exprs: list[ast.Expr] = []
            for name, chain in requested_fields.items():
                if name == "model_name":
                    exprs.append(ast.Alias(alias="model_name", expr=ast.Constant(value=model_table.model_name)))
                else:
                    exprs.append(ast.Alias(alias=name, expr=ast.Field(chain=[table_name, *chain])))

            inner_order_by, inner_limit = self._maybe_push_down_order_limit(node, table_name)

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

    def _maybe_push_down_order_limit(
        self, node: ast.SelectQuery, table_name: str
    ) -> tuple[list[ast.OrderExpr] | None, ast.Expr | None]:
        if not node or not node.order_by or not node.limit:
            return None, None

        # Only push down ORDER BY expressions that involve vector distance functions.
        # Non-distance expressions (e.g., ORDER BY timestamp) are left for the outer query,
        # as they may reference aliases or computed values not available in the inner query.
        rewriter = FieldReferenceRewriter("document_embeddings", table_name)
        inner_order_by = []
        for o in node.order_by:
            if is_vector_distance_order_by(o, node):
                resolved_expr = resolve_order_by_alias(o, node) or o.expr
                inner_order_by.append(ast.OrderExpr(expr=rewriter.visit(resolved_expr), order=o.order))

        if not inner_order_by:
            return None, None

        inner_limit = CloningVisitor(clear_locations=True).visit(node.limit)
        return inner_order_by, inner_limit

    def to_printed_clickhouse(self, context: HogQLContext):
        raise NotImplementedError("LazyTables cannot be printed to ClickHouse SQL")

    def to_printed_hogql(self):
        return "document_embeddings"


class RawDocumentEmbeddingsTable(Table):
    fields: dict[str, FieldOrTable] = DOCUMENT_EMBEDDINGS_FIELDS

    def to_printed_clickhouse(self, context: HogQLContext):
        return DOCUMENT_EMBEDDINGS_VIEW

    def to_printed_hogql(self):
        return "raw_document_embeddings"
