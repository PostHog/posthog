from typing import Optional

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_clickhouse_string
from posthog.hogql.parser import parse_expr

from posthog.schema_enums import InlineCohortCalculation


def inline_cohort_query(
    cohort_id: int,
    is_static: bool,
    version: Optional[int],
    context: HogQLContext,
) -> Optional[ast.SelectQuery | ast.SelectSetQuery]:
    if is_static:
        return None

    mode = context.modifiers.inlineCohortCalculation
    if mode == InlineCohortCalculation.OFF:
        return None

    # In AUTO mode the provider owns the verdict (feature flag + the cohort's recent
    # calculation history on the Django side); otherwise the modifier already decided.
    auto_gated = mode is None or mode == InlineCohortCalculation.AUTO
    return context.data.inline_cohort(cohort_id, auto_gated)


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
        matches = context.data.cohorts(int(arg.value), by="id")
        if len(matches) == 1:
            context.add_notice(
                start=arg.start,
                end=arg.end,
                message=f"Cohort #{matches[0].id} can also be specified as {escape_clickhouse_string(matches[0].name)}",
                fix=escape_clickhouse_string(matches[0].name),
            )
            inline_ast = inline_cohort_query(matches[0].id, matches[0].is_static, matches[0].version, context)
            if inline_ast is not None:
                return inline_ast
            return cohort_subquery(matches[0].id, matches[0].is_static, matches[0].version)
        raise QueryError(f"Could not find cohort with ID {arg.value}", node=arg)

    if isinstance(arg.value, str):
        matches = context.data.cohorts(arg.value, by="name")
        if len(matches) == 1:
            context.add_notice(
                start=arg.start,
                end=arg.end,
                message=f"Searching for cohort by name. Replace with numeric ID {matches[0].id} to protect against renaming.",
                fix=str(matches[0].id),
            )
            inline_ast = inline_cohort_query(matches[0].id, matches[0].is_static, matches[0].version, context)
            if inline_ast is not None:
                return inline_ast
            return cohort_subquery(matches[0].id, matches[0].is_static, matches[0].version)
        elif len(matches) > 1:
            raise QueryError(f"Found multiple cohorts with name '{arg.value}'", node=arg)
        raise QueryError(f"Could not find a cohort with the name '{arg.value}'", node=arg)

    raise QueryError("cohort() takes exactly one string or integer argument", node=arg)
