"""Turn a check definition into one count-only aggregate HogQL query.

Every check compiles to ``SELECT <aggregates> FROM (<failing rows>)``. Rows never leave
ClickHouse: the outer query only ever projects counts and numeric aggregates, which is what makes
it safe to store the result in the main Postgres.

``WarehouseColumnStatistics`` could short-circuit some of these (null counts, distinct counts) but
only for synced source tables at sync time, which is a second, subtly different set of semantics.
Left as a future fast-path rather than a silent inconsistency.
"""

from typing import Any

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_prepared_ast

from .contracts import CheckPlan, CompiledCheck, Evaluation, SubjectRef
from .errors import SubjectUnresolvableError
from .registry import get_spec

FAILURE_COUNT_ALIAS = "failure_count"
OBSERVED_VALUE_ALIAS = "observed_value"


def compile_check(
    *,
    check_type: str,
    subject: SubjectRef,
    column_name: str,
    config: dict[str, Any],
    related_subject: SubjectRef | None = None,
) -> CompiledCheck:
    if not subject.exists:
        raise SubjectUnresolvableError(f"The {subject.subject_type} {subject.subject_uuid} no longer resolves.")

    spec = get_spec(check_type)
    plan = spec.build(subject, column_name, spec.validate(config, column_name), related_subject)
    query = _aggregate(plan)
    return CompiledCheck(
        query=query,
        printed_query=_print(query),
        printed_failing_rows_query=_print(plan.diagnostic_rows or plan.failing_rows),
        evaluation=plan.evaluation,
    )


def _print(query: "ast.SelectQuery | ast.SelectSetQuery") -> str:
    # limit_top_select=False: the aggregate is a single row anyway, and the failing-rows form is
    # stored for a human to re-run, so a synthetic LIMIT would misrepresent what the check examined.
    return print_prepared_ast(
        query,
        context=HogQLContext(enable_select_queries=True, limit_top_select=False),
        dialect="hogql",
    )


def related_subject_ref(check_type: str, config: dict[str, Any]) -> tuple[str, str] | None:
    """The second subject this check needs resolved before it can compile, if any."""
    spec = get_spec(check_type)
    return spec.related_subject_ref(spec.parse_config(config))


def _aggregate(plan: CheckPlan) -> ast.SelectQuery:
    count_all = ast.Call(name="count", args=[])
    selects: list[ast.Expr] = []
    if plan.evaluation is Evaluation.ZERO_ROWS_PASS:
        selects.append(ast.Alias(alias=FAILURE_COUNT_ALIAS, expr=plan.failed_count_expr or count_all))
    selects.append(ast.Alias(alias=OBSERVED_VALUE_ALIAS, expr=plan.observed_value_expr or count_all))
    return ast.SelectQuery(select=selects, select_from=ast.JoinExpr(table=plan.failing_rows))
