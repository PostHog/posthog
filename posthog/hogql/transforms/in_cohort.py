from typing import Literal, Optional, cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_clickhouse_string
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import TraversingVisitor, clone_expr


def resolve_in_cohorts(
    node: _T_AST,
    dialect: Literal["hogql", "clickhouse"],
    stack: Optional[list[ast.SelectQuery]] = None,
    context: Optional[HogQLContext] = None,
):
    InCohortResolver(stack=stack, dialect=dialect, context=context).visit(node)


def resolve_in_cohorts_conjoined(
    node: ast.AST,
    dialect: Literal["hogql", "clickhouse"],
    context: HogQLContext,
    stack: Optional[list[ast.SelectQuery]] = None,
):
    MultipleInCohortResolver(stack=stack, dialect=dialect, context=context).visit(node)


class CohortCompareOperationTraverser(TraversingVisitor):
    ops: list[ast.CompareOperation] = []

    def __init__(self, expr: ast.Expr):
        self.ops = []
        super().visit(expr)

    def visit_compare_operation(self, node: ast.CompareOperation):
        if node.op == ast.CompareOperationOp.InCohort or node.op == ast.CompareOperationOp.NotInCohort:
            self.ops.append(node)


StaticOrDynamic = Literal["dynamic"] | Literal["static"]


class MultipleInCohortResolver(TraversingVisitor):
    dialect: Literal["hogql", "clickhouse"]

    def __init__(
        self,
        dialect: Literal["hogql", "clickhouse"],
        context: HogQLContext,
        stack: Optional[list[ast.SelectQuery]] = None,
    ):
        super().__init__()
        self.stack: list[ast.SelectQuery] = stack or []
        self.context = context
        self.dialect = dialect

    def visit_select_query(self, node: ast.SelectQuery):
        self.stack.append(node)

        super().visit_select_query(node)

        if node.where is not None:
            compare_operations = CohortCompareOperationTraverser(node.where).ops
            self._execute(node, compare_operations)

        self.stack.pop()

    def _execute(self, node: ast.SelectQuery, compare_operations: list[ast.CompareOperation]):
        if len(compare_operations) == 0:
            return

        cohorts = self._resolve_cohorts(compare_operations)
        self._add_join(cohorts=cohorts, select=node, compare_operations=compare_operations)

        for compare_node in compare_operations:
            compare_node.op = ast.CompareOperationOp.Eq
            compare_node.left = ast.Constant(value=1)
            compare_node.right = ast.Constant(value=1)

    def _resolve_cohorts(
        self, compare_operations: list[ast.CompareOperation]
    ) -> list[tuple[int, StaticOrDynamic, int]]:
        from posthog.models import Cohort

        cohorts: list[tuple[int, StaticOrDynamic, int]] = []

        for node in compare_operations:
            arg = node.right
            if not isinstance(arg, ast.Constant):
                raise QueryError("IN COHORT only works with constant arguments", node=arg)

            if (isinstance(arg.value, int) or isinstance(arg.value, float)) and not isinstance(arg.value, bool):
                int_cohorts = Cohort.objects.filter(
                    id=int(arg.value), team__project_id=self.context.project_id, deleted=False
                ).values_list("id", "is_static", "version")
                if len(int_cohorts) == 1:
                    if node.op == ast.CompareOperationOp.NotInCohort:
                        raise QueryError("NOT IN COHORT is not supported by this cohort mode")

                    id = int_cohorts[0][0]
                    is_static = int_cohorts[0][1]
                    version = int_cohorts[0][2] or 0

                    cohorts.append((id, "static" if is_static else "dynamic", version))
                    continue
                raise QueryError(f"Could not find cohort with ID {arg.value}", node=arg)

            if isinstance(arg.value, str):
                str_cohorts = Cohort.objects.filter(
                    name=arg.value, team__project_id=self.context.project_id, deleted=False
                ).values_list("id", "is_static", "version")
                if len(str_cohorts) == 1:
                    if node.op == ast.CompareOperationOp.NotInCohort:
                        raise QueryError("NOT IN COHORT is not supported by this cohort mode")

                    id = str_cohorts[0][0]
                    is_static = str_cohorts[0][1]
                    version = str_cohorts[0][2] or 0

                    cohorts.append((id, "static" if is_static else "dynamic", version))
                    continue
                elif len(str_cohorts) > 1:
                    raise QueryError(f"Found multiple cohorts with name '{arg.value}'", node=arg)
                raise QueryError(f"Could not find a cohort with the name '{arg.value}'", node=arg)

            raise QueryError("cohort() takes exactly one string or integer argument", node=arg)

        return cohorts

    def _add_join(
        self,
        cohorts: list[tuple[int, StaticOrDynamic, int]],
        select: ast.SelectQuery,
        compare_operations: list[ast.CompareOperation],
    ):
        must_add_join = True
        last_join = select.select_from

        while last_join:
            if isinstance(last_join.table, ast.Field) and last_join.table.chain[0] == "__in_cohort":
                must_add_join = False
                break
            if last_join.next_join:
                last_join = last_join.next_join
            else:
                break

        if must_add_join:
            static_cohorts = list(filter(lambda cohort: cohort[1] == "static", cohorts))
            dynamic_cohorts = list(filter(lambda cohort: cohort[1] == "dynamic", cohorts))

            any_static = len(static_cohorts) > 0
            any_dynamic = len(dynamic_cohorts) > 0

            def get_static_cohort_clause():
                return ast.CompareOperation(
                    left=ast.Field(chain=["cohort_id"]),
                    op=ast.CompareOperationOp.In,
                    right=ast.Array(exprs=[ast.Constant(value=id) for id, is_static, version in static_cohorts]),
                )

            def get_dynamic_cohort_clause():
                cohort_or = ast.Or(
                    exprs=[
                        ast.And(
                            exprs=[
                                ast.CompareOperation(
                                    left=ast.Field(chain=["cohort_id"]),
                                    op=ast.CompareOperationOp.Eq,
                                    right=ast.Constant(value=id),
                                ),
                                ast.CompareOperation(
                                    left=ast.Field(chain=["version"]),
                                    op=ast.CompareOperationOp.Eq,
                                    right=ast.Constant(value=version),
                                ),
                            ]
                        )
                        for id, is_static, version in dynamic_cohorts
                    ]
                )

                if len(cohort_or.exprs) == 1:
                    return cohort_or.exprs[0]

                return cohort_or

            # TODO: Extract these `SELECT` clauses out into their own vars and inject
            # via placeholders once the HogQL SELECT placeholders functionality is done
            if any_static and any_dynamic:
                static_clause = get_static_cohort_clause()
                dynamic_clause = get_dynamic_cohort_clause()

                table_query = parse_select(
                    """
                        SELECT person_id AS cohort_person_id, 1 AS matched, cohort_id
                        FROM static_cohort_people
                        WHERE {static_clause}
                        UNION ALL
                        SELECT person_id AS cohort_person_id, 1 AS matched, cohort_id
                        FROM raw_cohort_people
                        WHERE {dynamic_clause}
                    """,
                    placeholders={"static_clause": static_clause, "dynamic_clause": dynamic_clause},
                )
            elif any_static:
                clause = get_static_cohort_clause()
                table_query = parse_select(
                    """
                        SELECT person_id AS cohort_person_id, 1 AS matched, cohort_id
                        FROM static_cohort_people
                        WHERE {cohort_clause}
                    """,
                    placeholders={"cohort_clause": clause},
                )
            else:
                clause = get_dynamic_cohort_clause()
                table_query = parse_select(
                    """
                        SELECT person_id AS cohort_person_id, 1 AS matched, cohort_id
                        FROM raw_cohort_people
                        WHERE {cohort_clause}
                    """,
                    placeholders={"cohort_clause": clause},
                )

            new_join = ast.JoinExpr(
                alias=f"__in_cohort",
                table=table_query,
                join_type="LEFT JOIN",
                next_join=None,
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=1),
                    ),
                    constraint_type="ON",
                ),
            )

            new_join.constraint.expr.left = ast.Field(chain=[f"__in_cohort", "cohort_person_id"])  # type: ignore
            new_join.constraint.expr.right = clone_expr(compare_operations[0].left)  # type: ignore
            if last_join:
                last_join.next_join = new_join
            else:
                select.select_from = new_join

        cohort_match_compare_op = ast.CompareOperation(
            left=ast.Field(chain=["__in_cohort", "matched"]),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value=1),
        )

        if select.where is not None:
            select.where = ast.And(exprs=[select.where, cohort_match_compare_op])
        else:
            select.where = cohort_match_compare_op


class InCohortResolver(TraversingVisitor):
    def __init__(
        self,
        dialect: Literal["hogql", "clickhouse"],
        stack: Optional[list[ast.SelectQuery]] = None,
        context: Optional[HogQLContext] = None,
    ):
        super().__init__()
        self.stack: list[ast.SelectQuery] = stack or []
        self.context = context
        self.dialect = dialect

    def visit_select_query(self, node: ast.SelectQuery):
        self.stack.append(node)
        super().visit_select_query(node)
        self.stack.pop()

    def visit_compare_operation(self, node: ast.CompareOperation):
        if node.op == ast.CompareOperationOp.InCohort or node.op == ast.CompareOperationOp.NotInCohort:
            arg = node.right
            if not isinstance(arg, ast.Constant):
                raise QueryError("IN COHORT only works with constant arguments", node=arg)

            from posthog.models import Cohort

            if (isinstance(arg.value, int) or isinstance(arg.value, float)) and not isinstance(arg.value, bool):
                cohorts = Cohort.objects.filter(
                    id=int(arg.value), team__project_id=self.context.project_id, deleted=False
                ).values_list("id", "is_static", "version", "name")
                if len(cohorts) == 1:
                    self.context.add_notice(
                        start=arg.start,
                        end=arg.end,
                        message=f"Cohort #{cohorts[0][0]} can also be specified as {escape_clickhouse_string(cohorts[0][3])}",
                        fix=escape_clickhouse_string(cohorts[0][3]),
                    )
                    self._add_join_for_cohort(
                        cohort_id=cohorts[0][0],
                        is_static=cohorts[0][1],
                        version=cohorts[0][2],
                        compare=node,
                        select=self.stack[-1],
                        negative=node.op == ast.CompareOperationOp.NotInCohort,
                    )
                    return
                raise QueryError(f"Could not find cohort with ID {arg.value}", node=arg)

            if isinstance(arg.value, str):
                cohorts2 = Cohort.objects.filter(
                    name=arg.value, team__project_id=self.context.project_id, deleted=False
                ).values_list("id", "is_static", "version")
                if len(cohorts2) == 1:
                    self.context.add_notice(
                        start=arg.start,
                        end=arg.end,
                        message=f"Searching for cohort by name. Replace with numeric ID {cohorts2[0][0]} to protect against renaming.",
                        fix=str(cohorts2[0][0]),
                    )
                    self._add_join_for_cohort(
                        cohort_id=cohorts2[0][0],
                        is_static=cohorts2[0][1],
                        version=cohorts2[0][2],
                        compare=node,
                        select=self.stack[-1],
                        negative=node.op == ast.CompareOperationOp.NotInCohort,
                    )
                    return
                elif len(cohorts2) > 1:
                    raise QueryError(f"Found multiple cohorts with name '{arg.value}'", node=arg)
                raise QueryError(f"Could not find a cohort with the name '{arg.value}'", node=arg)
        else:
            self.visit(node.left)
            self.visit(node.right)

    def _add_join_for_cohort(
        self,
        cohort_id: int,
        is_static: bool,
        version: Optional[int],
        select: ast.SelectQuery,
        compare: ast.CompareOperation,
        negative: bool,
    ):
        must_add_join = True
        last_join = select.select_from
        while last_join:
            if isinstance(last_join.table, ast.Field) and last_join.table.chain[0] == f"in_cohort__{cohort_id}":
                must_add_join = False
                break
            if last_join.next_join:
                last_join = last_join.next_join
            else:
                break

        if must_add_join:
            if is_static:
                sql = "(SELECT person_id, 1 as matched FROM static_cohort_people WHERE cohort_id = {cohort_id})"
            elif version is not None:
                sql = "(SELECT person_id, 1 as matched FROM raw_cohort_people WHERE cohort_id = {cohort_id} AND version = {version})"
            else:
                sql = "(SELECT person_id, 1 as matched FROM raw_cohort_people WHERE cohort_id = {cohort_id} GROUP BY person_id, cohort_id, version HAVING sum(sign) > 0)"
            subquery = parse_expr(
                sql,
                {"cohort_id": ast.Constant(value=cohort_id), "version": ast.Constant(value=version)},
                start=None,  # clear the source start position
            )

            new_join = ast.JoinExpr(
                alias=f"in_cohort__{cohort_id}",
                table=subquery,
                join_type="LEFT JOIN",
                next_join=None,
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=1),
                    ),
                    constraint_type="ON",
                ),
            )
            new_join = cast(
                ast.JoinExpr,
                resolve_types(new_join, self.context, self.dialect, [self.stack[-1].type]),
            )
            new_join.constraint.expr.left = resolve_types(
                ast.Field(chain=[f"in_cohort__{cohort_id}", "person_id"]),
                self.context,
                self.dialect,
                [self.stack[-1].type],
            )
            new_join.constraint.expr.right = clone_expr(compare.left)
            if last_join:
                last_join.next_join = new_join
            else:
                select.select_from = new_join

        compare.op = ast.CompareOperationOp.NotEq if negative else ast.CompareOperationOp.Eq
        compare.left = resolve_types(
            ast.Field(chain=[f"in_cohort__{cohort_id}", "matched"]),
            self.context,
            self.dialect,
            [self.stack[-1].type],
        )
        compare.right = resolve_types(ast.Constant(value=1), self.context, self.dialect, [self.stack[-1].type])
