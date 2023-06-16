from typing import Set

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import HogQLException
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr


def resolve_cohort_subqueries(node: ast.Expr, context: HogQLContext = None) -> ast.Expr:
    from posthog.models import Cohort

    # find all cohorts
    cohort_finder = CohortFinder()
    cohort_finder.visit(node)

    if len(cohort_finder.cohorts) == 0:
        return node

    # fetch them
    cohorts = Cohort.objects.filter(id__in=cohort_finder.cohorts, team_id=context.team_id).values_list(
        "id", "is_static"
    )
    static_cohorts = set(id for id, is_static in cohorts if is_static)

    if len(cohort_finder.cohorts) != len(cohorts):
        missing_cohorts = [str(a) for a in (set(cohort_finder.cohorts) - set(id for id, _ in cohorts))]
        raise HogQLException(
            f"Could not find cohort{'s' if len(missing_cohorts) > 1 else ''}: {', '.join(missing_cohorts)}"
        )

    node = CohortSwapper(static_cohorts=static_cohorts, context=context).visit(node)
    return node


class CohortFinder(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.cohorts: Set[int] = set()

    def visit_compare_operation(self, node: ast.CompareOperation):
        if node.op == ast.CompareOperationOp.InCohort or node.op == ast.CompareOperationOp.NotInCohort:
            if not isinstance(node.right, ast.Constant) or not isinstance(node.right.value, int):
                raise HogQLException("Cohort id must be a constant integer")
            self.cohorts.add(node.right.value)


class CohortSwapper(CloningVisitor):
    def __init__(self, context: HogQLContext, static_cohorts: Set[int]):
        super().__init__(clear_types=False)
        self.static_cohorts = static_cohorts
        self.context = context

    def visit_compare_operation(self, node: ast.CompareOperation):
        from posthog.hogql.property import cohort_subquery
        from posthog.hogql.printer import prepare_ast_for_printing

        if node.op == ast.CompareOperationOp.InCohort or node.op == ast.CompareOperationOp.NotInCohort:
            if not isinstance(node.right, ast.Constant) or not isinstance(node.right.value, int):
                raise HogQLException("Cohort id must be a constant integer")
            cohort_id = node.right.value
            node = clone_expr(node)
            node.left = super().visit(node.left)
            node.op = (
                ast.CompareOperationOp.In
                if node.op == ast.CompareOperationOp.InCohort
                else ast.CompareOperationOp.NotIn
            )
            node.right = cohort_subquery(cohort_id, cohort_id in self.static_cohorts)
            node.right = prepare_ast_for_printing(node.right, context=self.context, dialect="clickhouse")
            return node
        return node
