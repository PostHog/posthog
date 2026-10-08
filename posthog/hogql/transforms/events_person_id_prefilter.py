from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.lazy_join_tags import PERSON_DISTINCT_ID_OVERRIDES
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.where_clause_extractor import (
    contains_row_multiplying_function,
    extract_uuid_constants,
    top_level_conjuncts,
)
from posthog.hogql.helpers.timestamp_visitor import is_time_or_interval_constant
from posthog.hogql.resolver import ResolverFactory, resolve_types
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.schema_enums import PersonsOnEventsMode

PERSON_ID_PREFILTER_MAX_IDS = 100
_NONDETERMINISTIC_FUNCTIONS = frozenset({"rand", "rownumberinblock", "rownumberinallblocks", "nowinblock"})


class _UnsupportedQueryFinder(TraversingVisitor):
    def __init__(self, root: ast.SelectQuery) -> None:
        super().__init__()
        self.root = root
        self.found = False

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node is not self.root:
            self.found = True
        else:
            super().visit_select_query(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.found = True

    def visit_call(self, node: ast.Call) -> None:
        if node.name.lower() in _NONDETERMINISTIC_FUNCTIONS:
            self.found = True
        super().visit_call(node)


class EventsPersonIdPrefilter:
    def __init__(self, context: HogQLContext, resolver_factory: ResolverFactory | None = None) -> None:
        self.context = context
        self.resolver_factory = resolver_factory

    @staticmethod
    def _unwrap(expr: ast.Expr) -> ast.Expr:
        while isinstance(expr, ast.Alias):
            expr = expr.expr
        return expr

    @classmethod
    def _field_type(cls, expr: ast.Expr) -> ast.FieldType | None:
        expr = cls._unwrap(expr)
        return expr.type if isinstance(expr, ast.Field) and isinstance(expr.type, ast.FieldType) else None

    @classmethod
    def _direct_field(cls, expr: ast.Expr, name: str, owner: ast.TableType | ast.TableAliasType) -> bool:
        field = cls._field_type(expr)
        return field is not None and field.name == name and field.table_type is owner

    @classmethod
    def _override_field(cls, expr: ast.Expr, name: str, owner: ast.TableType | ast.TableAliasType) -> bool:
        field = cls._field_type(expr)
        return (
            field is not None
            and field.name == name
            and isinstance(field.table_type, ast.LazyJoinType)
            and field.table_type.table_type is owner
            and field.table_type.field == "override"
            and field.table_type.lazy_join.resolver == PERSON_DISTINCT_ID_OVERRIDES
        )

    @classmethod
    def _resolved_person_id(cls, expr: ast.Expr, owner: ast.TableType | ast.TableAliasType) -> bool:
        expr = cls._unwrap(expr)
        if not isinstance(expr, ast.Call) or expr.name != "if" or len(expr.args) != 3:
            return False
        condition, overridden, stored = expr.args
        if not cls._override_field(overridden, "person_id", owner) or not cls._direct_field(
            stored, "event_person_id", owner
        ):
            return False
        if not isinstance(condition, ast.Call) or condition.name != "not" or len(condition.args) != 1:
            return False
        empty = condition.args[0]
        return (
            isinstance(empty, ast.Call)
            and empty.name == "empty"
            and len(empty.args) == 1
            and cls._override_field(empty.args[0], "distinct_id", owner)
        )

    @classmethod
    def _timestamp_bound(cls, term: ast.Expr, owner: ast.TableType | ast.TableAliasType) -> bool:
        if not isinstance(term, ast.CompareOperation) or term.op not in (
            ast.CompareOperationOp.Gt,
            ast.CompareOperationOp.GtEq,
            ast.CompareOperationOp.Lt,
            ast.CompareOperationOp.LtEq,
        ):
            return False
        return (cls._direct_field(term.left, "timestamp", owner) and is_time_or_interval_constant(term.right)) or (
            cls._direct_field(term.right, "timestamp", owner) and is_time_or_interval_constant(term.left)
        )

    def apply(self, node: _T_AST) -> _T_AST:
        if (
            not self.context.modifiers.personIdFilterPrewhere
            or self.context.modifiers.personsOnEventsMode
            not in (
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
            )
            or not isinstance(node, ast.SelectQuery)
            or node.type is None
            or node.where is None
            or node.prewhere is not None
            or node.ctes
            or node.array_join_op is not None
        ):
            return node
        source = node.select_from
        if (
            source is None
            or not isinstance(source.table, ast.Field)
            or source.next_join is not None
            or source.column_aliases
            or source.sample is not None
            or source.table_final
            or not isinstance(source.type, (ast.TableType, ast.TableAliasType))
        ):
            return node
        owner = source.type
        table_type = owner.table_type if isinstance(owner, ast.TableAliasType) else owner
        if not isinstance(table_type, ast.TableType) or not isinstance(table_type.table, EventsTable):
            return node
        unsupported = _UnsupportedQueryFinder(node)
        unsupported.visit(node)
        if unsupported.found or contains_row_multiplying_function(node):
            return node

        terms = top_level_conjuncts(node.where)
        for term in terms:
            if not isinstance(term, ast.CompareOperation) or not self._resolved_person_id(term.left, owner):
                continue
            if not (
                (term.op == ast.CompareOperationOp.Eq and isinstance(term.right, ast.Constant))
                or (term.op == ast.CompareOperationOp.In and isinstance(term.right, ast.Tuple))
            ):
                continue
            constants = extract_uuid_constants(term.right)
            if not constants or len(constants) > PERSON_ID_PREFILTER_MAX_IDS:
                continue
            alias = source.alias or "events"
            candidate_ids = ast.SelectQuery(
                select=[ast.Field(chain=["distinct_id"])],
                select_from=ast.JoinExpr(table=ast.Field(chain=["raw_person_distinct_id_overrides"])),
                where=ast.CompareOperation(
                    op=term.op, left=ast.Field(chain=["person_id"]), right=clone_expr(term.right, clear_types=True)
                ),
            )
            # Raw versions include detached history. The original resolved filter rejects stale ownership.
            # Keep IN local so candidates come from the same replica as the override join.
            candidates = ast.Or(
                exprs=[
                    ast.CompareOperation(
                        op=term.op,
                        left=ast.Field(chain=[alias, "event_person_id"]),
                        right=clone_expr(term.right, clear_types=True),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=ast.Field(chain=[alias, "distinct_id"]),
                        right=candidate_ids,
                    ),
                ]
            )
            prewhere = ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=[alias, "team_id"]),
                        right=ast.Constant(value=self.context.team_id),
                    ),
                    candidates,
                ]
            )
            prewhere = resolve_types(
                prewhere, self.context, "clickhouse", scopes=[node.type], resolver_factory=self.resolver_factory
            )
            # Re-resolving typed bounds adds hidden aliases that prevent timestamp index pruning.
            prewhere.exprs[1:1] = [clone_expr(bound) for bound in terms if self._timestamp_bound(bound, owner)]
            node.prewhere = prewhere
            break
        return node
