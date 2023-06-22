from typing import List

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import HogQLException


def cohort(node: ast.Expr, args: List[ast.Expr], context: HogQLContext) -> ast.Expr:
    if len(args) != 1:
        raise HogQLException("cohort() takes exactly one argument", node=node)

    arg = args[0]
    if not isinstance(arg, ast.Constant):
        raise HogQLException("cohort() takes only constant arguments", node=arg)

    from posthog.models import Cohort
    from posthog.hogql.parser import parse_expr

    def cohort_subquery(cohort_id, is_static) -> ast.Expr:
        if is_static:
            sql = "(SELECT person_id FROM static_cohort_people WHERE cohort_id = {cohort_id})"
        else:
            sql = "(SELECT person_id FROM raw_cohort_people WHERE cohort_id = {cohort_id} GROUP BY person_id, cohort_id, version HAVING sum(sign) > 0)"
        return parse_expr(sql, {"cohort_id": ast.Constant(value=cohort_id)})

    if isinstance(arg.value, int) and not isinstance(arg.value, bool):
        cohorts = Cohort.objects.filter(id=arg.value, team_id=context.team_id).values_list("id", "is_static")
        if len(cohorts) == 1:
            return cohort_subquery(cohorts[0][0], cohorts[0][1])
        raise HogQLException(f"Could not find cohort with id {arg.value}", node=arg)

    if isinstance(arg.value, str):
        cohorts = Cohort.objects.filter(name=arg.value, team_id=context.team_id).values_list("id", "is_static")
        if len(cohorts) == 1:
            return cohort_subquery(cohorts[0][0], cohorts[0][1])
        elif len(cohorts) > 1:
            raise HogQLException(f"Found multiple cohorts with name '{arg.value}'", node=arg)
        raise HogQLException(f"Could not find a cohort with the name '{arg.value}'", node=arg)

    raise HogQLException("cohort() takes exactly one string or integer argument", node=arg)
