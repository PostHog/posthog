from typing import List

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import HogQLException
from posthog.hogql.escape_sql import escape_clickhouse_string
from posthog.schema import HogQLNotice


def cohort(node: ast.Expr, args: List[ast.Expr], context: HogQLContext) -> ast.Expr:
    arg = args[0]
    if not isinstance(arg, ast.Constant):
        raise HogQLException("cohort() takes only constant arguments", node=arg)

    from posthog.models import Cohort
    from posthog.hogql.property import cohort_subquery

    if isinstance(arg.value, int) and not isinstance(arg.value, bool):
        cohorts = Cohort.objects.filter(id=arg.value, team_id=context.team_id).values_list("id", "is_static", "name")
        if len(cohorts) == 1:
            context.notices.append(
                HogQLNotice(
                    start=arg.start,
                    end=arg.end,
                    message=f"Cohort #{cohorts[0][0]} can also be specified as {escape_clickhouse_string(cohorts[0][2])}",
                    fix=escape_clickhouse_string(cohorts[0][2]),
                )
            )
            return cohort_subquery(cohorts[0][0], cohorts[0][1])
        raise HogQLException(f"Could not find cohort with id {arg.value}", node=arg)

    if isinstance(arg.value, str):
        cohorts = Cohort.objects.filter(name=arg.value, team_id=context.team_id).values_list("id", "is_static")
        if len(cohorts) == 1:
            context.notices.append(
                HogQLNotice(
                    start=arg.start,
                    end=arg.end,
                    message=f"Searching for cohort by name. Replace with numeric ID {cohorts[0][0]} to protect against renaming.",
                    fix=str(cohorts[0][0]),
                )
            )
            return cohort_subquery(cohorts[0][0], cohorts[0][1])
        elif len(cohorts) > 1:
            raise HogQLException(f"Found multiple cohorts with name '{arg.value}'", node=arg)
        raise HogQLException(f"Could not find a cohort with the name '{arg.value}'", node=arg)

    raise HogQLException("cohort() takes exactly one string or integer argument", node=arg)
