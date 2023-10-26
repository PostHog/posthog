from typing import List, Optional, cast

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import HogQLException
from posthog.hogql.escape_sql import escape_clickhouse_string
from posthog.hogql.parser import parse_expr
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import TraversingVisitor, clone_expr


def resolve_in_cohorts(
    node: ast.Expr,
    stack: Optional[List[ast.SelectQuery]] = None,
    context: HogQLContext = None,
):
    InCohortResolver(stack=stack, context=context).visit(node)


class InCohortResolver(TraversingVisitor):
    def __init__(
        self,
        stack: Optional[List[ast.SelectQuery]] = None,
        context: HogQLContext = None,
    ):
        super().__init__()
        self.stack: List[ast.SelectQuery] = stack or []
        self.context = context

    def visit_select_query(self, node: ast.SelectQuery):
        self.stack.append(node)
        super().visit_select_query(node)
        self.stack.pop()

    def visit_compare_operation(self, node: ast.CompareOperation):
        if node.op == ast.CompareOperationOp.InCohort or node.op == ast.CompareOperationOp.NotInCohort:
            arg = node.right
            if not isinstance(arg, ast.Constant):
                raise HogQLException("IN COHORT only works with constant arguments", node=arg)

            from posthog.models import Cohort

            if isinstance(arg.value, int) and not isinstance(arg.value, bool):
                cohorts = Cohort.objects.filter(id=arg.value, team_id=self.context.team_id).values_list(
                    "id", "is_static", "name"
                )
                if len(cohorts) == 1:
                    self.context.add_notice(
                        start=arg.start,
                        end=arg.end,
                        message=f"Cohort #{cohorts[0][0]} can also be specified as {escape_clickhouse_string(cohorts[0][2])}",
                        fix=escape_clickhouse_string(cohorts[0][2]),
                    )
                    self._add_join_for_cohort(
                        cohort_id=cohorts[0][0],
                        is_static=cohorts[0][1],
                        compare=node,
                        select=self.stack[-1],
                        negative=node.op == ast.CompareOperationOp.NotInCohort,
                    )
                    return
                raise HogQLException(f"Could not find cohort with id {arg.value}", node=arg)

            if isinstance(arg.value, str):
                cohorts = Cohort.objects.filter(name=arg.value, team_id=self.context.team_id).values_list(
                    "id", "is_static"
                )
                if len(cohorts) == 1:
                    self.context.add_notice(
                        start=arg.start,
                        end=arg.end,
                        message=f"Searching for cohort by name. Replace with numeric ID {cohorts[0][0]} to protect against renaming.",
                        fix=str(cohorts[0][0]),
                    )
                    self._add_join_for_cohort(
                        cohort_id=cohorts[0][0],
                        is_static=cohorts[0][1],
                        compare=node,
                        select=self.stack[-1],
                        negative=node.op == ast.CompareOperationOp.NotInCohort,
                    )
                    return
                elif len(cohorts) > 1:
                    raise HogQLException(f"Found multiple cohorts with name '{arg.value}'", node=arg)
                raise HogQLException(f"Could not find a cohort with the name '{arg.value}'", node=arg)
        else:
            self.visit(node.left)
            self.visit(node.right)

    def _add_join_for_cohort(
        self,
        cohort_id: int,
        is_static: bool,
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
            else:
                sql = "(SELECT person_id, 1 as matched FROM raw_cohort_people WHERE cohort_id = {cohort_id} GROUP BY person_id, cohort_id, version HAVING sum(sign) > 0)"
            subquery = parse_expr(
                sql, {"cohort_id": ast.Constant(value=cohort_id)}, start=None
            )  # clear the source start position

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
                    )
                ),
            )
            new_join = cast(
                ast.JoinExpr,
                resolve_types(new_join, self.context, [self.stack[-1].type]),
            )
            new_join.constraint.expr.left = resolve_types(
                ast.Field(chain=[f"in_cohort__{cohort_id}", "person_id"]),
                self.context,
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
            [self.stack[-1].type],
        )
        compare.right = resolve_types(ast.Constant(value=1), self.context, [self.stack[-1].type])
