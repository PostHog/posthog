from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor


class _UnsafeExpressions(TraversingVisitor):
    def __init__(self, *, reject_subqueries: bool = True, outer_aliases: set[str] | None = None) -> None:
        super().__init__()
        self.found = False
        self.reject_subqueries = reject_subqueries
        self.scopes = [outer_aliases or set()]
        self.owned_aliases = outer_aliases if reject_subqueries else None

    def visit_field(self, node: ast.Field) -> None:
        if self.owned_aliases is not None and len(node.chain) > 1 and node.chain[0] not in self.owned_aliases:
            field_type = node.type
            while isinstance(field_type, ast.FieldAliasType):
                field_type = field_type.type
            table_type = field_type.table_type if isinstance(field_type, ast.FieldType) else None
            while isinstance(table_type, (ast.LazyJoinType, ast.VirtualTableType)):
                table_type = table_type.table_type
            if (
                not isinstance(table_type, (ast.TableAliasType, ast.SelectQueryAliasType, ast.CTETableAliasType))
                or table_type.alias not in self.owned_aliases
            ):
                self.found = True
        if (
            len(node.chain) > 1
            and node.chain[0] not in self.scopes[-1]
            and any(node.chain[0] in scope for scope in self.scopes[:-1])
        ):
            self.found = True

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if self.reject_subqueries:
            self.found = True
            return
        aliases: set[str] = set()
        join = node.select_from
        while join is not None:
            alias = CrossJoinOptimizer._alias(join)
            if alias is not None:
                aliases.add(alias)
            join = join.next_join
        self.scopes.append(aliases)
        super().visit_select_query(node)
        self.scopes.pop()

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        if self.reject_subqueries:
            self.found = True
        else:
            super().visit_select_set_query(node)

    def visit_call(self, node: ast.Call) -> None:
        if node.name.lower().startswith(("rand", "generateuuid", "rownumberin", "running", "neighbor")):
            self.found = True
        super().visit_call(node)


class DirectEqualities(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.aliases: dict[tuple[int, int], tuple[str, str]] = {}

    def visit_field(self, node: ast.Field) -> None:
        pass

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        if (
            node.op == ast.CompareOperationOp.Eq
            and node.start is not None
            and node.end is not None
            and isinstance(node.left, ast.Field)
            and isinstance(node.right, ast.Field)
            and len(node.left.chain) == len(node.right.chain) == 2
            and isinstance(node.left.chain[0], str)
            and isinstance(node.right.chain[0], str)
        ):
            self.aliases[node.start, node.end] = (node.left.chain[0], node.right.chain[0])
        super().visit_compare_operation(node)


class CrossJoinOptimizer(TraversingVisitor):
    def __init__(self, context: HogQLContext, direct_equalities: DirectEqualities) -> None:
        super().__init__()
        self.context = context
        self.direct_equalities = direct_equalities

    def visit_field(self, node: ast.Field) -> None:
        # Type graphs point back into SELECTs; only visit the query's expression tree.
        pass

    @staticmethod
    def _key_field(node: ast.Expr) -> ast.Field | None:
        while isinstance(node, ast.Alias):
            node = node.expr
        return node if isinstance(node, ast.Field) else None

    def _non_nullable_key(self, node: ast.Expr) -> bool:
        if node.type is None:
            return False
        try:
            return not node.type.resolve_constant_type(self.context).nullable
        except (NotImplementedError, KeyError):
            return False

    @staticmethod
    def _alias(join: ast.JoinExpr) -> str | None:
        if join.alias:
            return join.alias
        if isinstance(join.table, ast.Field) and len(join.table.chain) == 1:
            return str(join.table.chain[0])
        return None

    @staticmethod
    def _conjuncts(node: ast.Expr) -> list[ast.Expr]:
        if isinstance(node, ast.And):
            return [part for expr in node.exprs for part in CrossJoinOptimizer._conjuncts(expr)]
        return [node]

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        super().visit_select_query(node)
        left = node.select_from
        right = left.next_join if left else None
        if (
            left is None
            or right is None
            or right.next_join is not None
            or right.join_type != "CROSS JOIN"
            or right.constraint is not None
            or node.where is None
            or node.array_join_list
            or left.sample is not None
            or right.sample is not None
            or left.table_args
            or right.table_args
        ):
            return
        left_alias, right_alias = self._alias(left), self._alias(right)
        if left_alias is None or right_alias is None or left_alias == right_alias:
            return
        aliases = {left_alias, right_alias}
        unsafe = _UnsafeExpressions(outer_aliases=aliases)
        unsafe.visit(node.where)
        for expr in node.select:
            unsafe.visit(expr)
        sources = _UnsafeExpressions(reject_subqueries=False, outer_aliases=aliases)
        sources.visit(left.table)
        sources.visit(right.table)
        if unsafe.found or sources.found:
            return
        keys: list[ast.Expr] = []
        residuals: list[ast.Expr] = []
        for expr in self._conjuncts(node.where):
            left_key = self._key_field(expr.left) if isinstance(expr, ast.CompareOperation) else None
            right_key = self._key_field(expr.right) if isinstance(expr, ast.CompareOperation) else None
            if (
                isinstance(expr, ast.CompareOperation)
                and expr.op == ast.CompareOperationOp.Eq
                and self._non_nullable_key(expr.left)
                and self._non_nullable_key(expr.right)
                and (
                    (
                        expr.start is not None
                        and expr.end is not None
                        and self.direct_equalities.aliases.get((expr.start, expr.end)) is not None
                        and self.direct_equalities.aliases[expr.start, expr.end]
                        in ((left_alias, right_alias), (right_alias, left_alias))
                    )
                    or (
                        left_key is not None
                        and right_key is not None
                        and len(left_key.chain) == len(right_key.chain) == 2
                        and {left_key.chain[0], right_key.chain[0]} == aliases
                    )
                )
            ):
                keys.append(expr)
            else:
                residuals.append(expr)
        if not keys:
            return
        # HogQL WHERE equality matches two NULLs, whereas JOIN equality does not.
        # Only non-nullable keys can move; ALL preserves the CROSS JOIN's duplicates.
        right.join_type = "ALL INNER JOIN"
        right.constraint = ast.JoinConstraint(
            expr=keys[0] if len(keys) == 1 else ast.And(exprs=keys), constraint_type="ON"
        )
        node.where = residuals[0] if len(residuals) == 1 else ast.And(exprs=residuals) if residuals else None


def optimize_cross_joins(node: ast.AST, context: HogQLContext, direct_equalities: DirectEqualities) -> None:
    CrossJoinOptimizer(context, direct_equalities).visit(node)


class _LocalPredicate(TraversingVisitor):
    def __init__(self, alias: str) -> None:
        super().__init__()
        self.alias = alias
        self.safe = True
        self.has_field = False

    def visit_field(self, node: ast.Field) -> None:
        self.has_field = True
        if len(node.chain) != 2 or node.chain[0] != self.alias:
            self.safe = False

    def visit_call(self, node: ast.Call) -> None:
        if node.name not in {
            "toDateTime",
            "toDateTime64",
            "toDate",
            "toTimeZone",
            "toStartOfDay",
            "now",
            "today",
            "toIntervalDay",
            "toIntervalHour",
            "toIntervalMinute",
        }:
            self.safe = False
        super().visit_call(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.safe = False

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.safe = False


class _PredicateCloner(CloningVisitor):
    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        return self.visit(node.expr)


def local_cross_join_predicates(where: ast.Expr | None, alias: str) -> ast.Expr | None:
    predicates: list[ast.Expr] = []
    for expr in CrossJoinOptimizer._conjuncts(where) if where is not None else []:
        if not isinstance(expr, (ast.CompareOperation, ast.BetweenExpr)):
            continue
        local = _LocalPredicate(alias)
        local.visit(expr)
        if local.safe and local.has_field:
            predicates.append(_PredicateCloner(clear_types=True).visit(expr))
    return ast.And(exprs=predicates) if predicates else None
