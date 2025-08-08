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

    if (isinstance(arg.value, int) or isinstance(arg.value, float)) and not isinstance(arg.value, bool):
        if not context.data_bundle:
            raise QueryError("Cohort lookup requires data bundle in context", node=arg)
        
        cohort = context.data_bundle.get_cohort_by_id(int(arg.value))
        if cohort:
            context.add_notice(
                start=arg.start,
                end=arg.end,
                message=f"Cohort #{cohort.id} can also be specified as {escape_clickhouse_string(cohort.name)}",
                fix=escape_clickhouse_string(cohort.name) if cohort.name else None,
            )
            return cohort_subquery(cohort.id, cohort.is_static, None)  # version not available in dataclass
        raise QueryError(f"Could not find cohort with ID {arg.value}", node=arg)

    if isinstance(arg.value, str):
        if not context.data_bundle:
            raise QueryError("Cohort lookup requires data bundle in context", node=arg)
        
        cohort = context.data_bundle.get_cohort_by_name(arg.value)
        if cohort:
            context.add_notice(
                start=arg.start,
                end=arg.end,
                message=f"Searching for cohort by name. Replace with numeric ID {cohort.id} to protect against renaming.",
                fix=str(cohort.id),
            )
            return cohort_subquery(cohort.id, cohort.is_static, None)  # version not available in dataclass
        raise QueryError(f"Could not find a cohort with the name '{arg.value}'", node=arg)

    raise QueryError("cohort() takes exactly one string or integer argument", node=arg)
