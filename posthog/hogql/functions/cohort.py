import datetime
from typing import Optional

from django.utils import timezone

import posthoganalytics

from posthog.schema import InlineCohortCalculation

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_clickhouse_string
from posthog.hogql.parser import parse_expr

INLINE_COHORT_THRESHOLD_SECONDS = 10


def _is_inline_flag_enabled(context: HogQLContext) -> bool:
    from posthog.models import Team

    if not context.team:
        context.team = Team.objects.get(id=context.team_id)
    team = context.team
    return bool(
        posthoganalytics.feature_enabled(
            "inline-cohort-calculation",
            str(team.uuid),
            groups={
                "organization": str(team.organization_id),
                "project": str(team.id),
            },
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )


def _is_cohort_fast_enough_to_inline(cohort_id: int) -> bool:
    from posthog.models.cohort.calculation_history import CohortCalculationHistory

    seven_days_ago = timezone.now() - datetime.timedelta(days=7)
    recent_calcs = list(
        CohortCalculationHistory.objects.filter(
            cohort_id=cohort_id,
            finished_at__isnull=False,
            started_at__gte=seven_days_ago,
        )
        .order_by("-started_at")
        .values_list("error", "started_at", "finished_at")
    )
    if not recent_calcs:
        return True

    if recent_calcs[0][0] is not None:
        return False

    durations = sorted(
        (finished_at - started_at).total_seconds() for error, started_at, finished_at in recent_calcs if error is None
    )
    return not durations or durations[len(durations) // 2] < INLINE_COHORT_THRESHOLD_SECONDS


def inline_cohort_query(
    cohort_id: int,
    is_static: bool,
    version: Optional[int],
    context: HogQLContext,
) -> Optional[ast.SelectQuery | ast.SelectSetQuery]:
    from posthog.hogql_queries.hogql_cohort_query import HogQLCohortQuery
    from posthog.models import Cohort

    if is_static:
        return None

    mode = context.modifiers.inlineCohortCalculation
    if mode == InlineCohortCalculation.OFF:
        return None

    if mode is None or mode == InlineCohortCalculation.AUTO:
        if not _is_inline_flag_enabled(context):
            return None
        if not _is_cohort_fast_enough_to_inline(cohort_id):
            return None

    cohort = Cohort.objects.get(id=cohort_id, team__project_id=context.project_id)

    if not context.team:
        from posthog.models import Team

        context.team = Team.objects.get(id=context.team_id)

    return HogQLCohortQuery(cohort=cohort, team=context.team).get_query()


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
    from posthog.models import Cohort

    arg = args[0]
    if not isinstance(arg, ast.Constant):
        raise QueryError("cohort() takes only constant arguments", node=arg)

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
            inline_ast = inline_cohort_query(cohorts1[0][0], cohorts1[0][1], cohorts1[0][2], context)
            if inline_ast is not None:
                return inline_ast
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
            inline_ast = inline_cohort_query(cohorts2[0][0], cohorts2[0][1], cohorts2[0][2], context)
            if inline_ast is not None:
                return inline_ast
            return cohort_subquery(cohorts2[0][0], cohorts2[0][1], cohorts2[0][2])
        elif len(cohorts2) > 1:
            raise QueryError(f"Found multiple cohorts with name '{arg.value}'", node=arg)
        raise QueryError(f"Could not find a cohort with the name '{arg.value}'", node=arg)

    raise QueryError("cohort() takes exactly one string or integer argument", node=arg)
