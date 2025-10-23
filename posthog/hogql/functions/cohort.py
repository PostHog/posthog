from typing import Optional

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_clickhouse_string
from posthog.hogql.parser import parse_expr


def cohort_subquery(cohort_id, is_static, version: Optional[int] = None) -> ast.Expr:
    if is_static:
        sql = "(SELECT person_id FROM static_cohort_people WHERE cohort_id = {cohort_id})"
    elif version is not None:
        sql = "(SELECT person_id FROM raw_cohort_people WHERE cohort_id = {cohort_id} AND version = {version})"
    else:
        sql = "(SELECT person_id FROM raw_cohort_people WHERE cohort_id = {cohort_id} GROUP BY person_id, cohort_id, version HAVING sum(sign) > 0)"
    return parse_expr(
        sql, {"cohort_id": ast.Constant(value=cohort_id), "version": ast.Constant(value=version)}, start=None
    )  # clear the source start position


def cohort_query_node(node: ast.Expr, context: HogQLContext) -> ast.Expr:
    return cohort(node, [node], context)


def cohort(node: ast.Expr, args: list[ast.Expr], context: HogQLContext) -> ast.Expr:
    arg = args[0]
    if not isinstance(arg, ast.Constant):
        raise QueryError("cohort() takes only constant arguments", node=arg)

    from posthog.models import Cohort

    if (isinstance(arg.value, int) or isinstance(arg.value, float)) and not isinstance(arg.value, bool):
        cohorts1 = Cohort.objects.filter(
            id=int(arg.value), team__project_id=context.project_id, deleted=False
        ).values_list("id", "is_static", "version", "name")
        if len(cohorts1) == 1:
            context.add_notice(
                start=arg.start,
                end=arg.end,
                message=f"Cohort #{cohorts1[0][0]} can also be specified as {escape_clickhouse_string(cohorts1[0][3])}",
                fix=escape_clickhouse_string(cohorts1[0][3]),
            )
            return cohort_subquery(cohorts1[0][0], cohorts1[0][1], cohorts1[0][2])
        raise QueryError(f"Could not find cohort with ID {arg.value}", node=arg)

    if isinstance(arg.value, str):
        cohorts2 = Cohort.objects.filter(
            name=arg.value, team__project_id=context.project_id, deleted=False
        ).values_list("id", "is_static", "version")
        if len(cohorts2) == 1:
            context.add_notice(
                start=arg.start,
                end=arg.end,
                message=f"Searching for cohort by name. Replace with numeric ID {cohorts2[0][0]} to protect against renaming.",
                fix=str(cohorts2[0][0]),
            )
            return cohort_subquery(cohorts2[0][0], cohorts2[0][1], cohorts2[0][2])
        elif len(cohorts2) > 1:
            raise QueryError(f"Found multiple cohorts with name '{arg.value}'", node=arg)
        raise QueryError(f"Could not find a cohort with the name '{arg.value}'", node=arg)

    raise QueryError("cohort() takes exactly one string or integer argument", node=arg)
