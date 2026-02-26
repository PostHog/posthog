import datetime
from typing import Optional

from django.db import models
from django.utils import timezone

import posthoganalytics

from posthog.schema import InlineCohortCalculation

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_clickhouse_string
from posthog.hogql.parser import parse_expr

INLINE_COHORT_THRESHOLD_SECONDS = 10


def should_inline_based_on_durations(
    durations: list[float], threshold: float = INLINE_COHORT_THRESHOLD_SECONDS
) -> bool:
    if not durations:
        return False
    sorted_durations = sorted(durations)
    return sorted_durations[len(sorted_durations) // 2] < threshold


def get_cohort_subquery_or_inline(
    cohort_id: int,
    is_static: bool,
    version: Optional[int],
    context: HogQLContext,
) -> Optional[ast.SelectQuery | ast.SelectSetQuery]:
    from posthog.hogql_queries.hogql_cohort_query import HogQLCohortQuery
    from posthog.models import Cohort, Team
    from posthog.models.cohort.calculation_history import CohortCalculationHistory

    if is_static:
        return None

    mode = context.modifiers.inlineCohortCalculation
    if mode == InlineCohortCalculation.OFF:
        return None

    if mode is None or mode == InlineCohortCalculation.AUTO:
        team = context.team or Team.objects.get(id=context.team_id)
        flag_enabled = posthoganalytics.feature_enabled(
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
        if not flag_enabled:
            return None

        newest_calc = (
            CohortCalculationHistory.objects.filter(
                cohort_id=cohort_id,
                finished_at__isnull=False,
            )
            .order_by("-started_at")
            .values("error")
            .first()
        )
        if newest_calc is not None:
            if newest_calc["error"] is not None:
                return None

            seven_days_ago = timezone.now() - datetime.timedelta(days=7)
            durations = list(
                CohortCalculationHistory.objects.filter(
                    cohort_id=cohort_id,
                    finished_at__isnull=False,
                    error__isnull=True,
                    started_at__gte=seven_days_ago,
                )
                .annotate(duration=models.F("finished_at") - models.F("started_at"))
                .values_list("duration", flat=True)
            )
            if not should_inline_based_on_durations([d.total_seconds() for d in durations]):
                return None

    cohort = Cohort.objects.get(id=cohort_id, team__project_id=context.project_id)
    if not cohort.properties.flat:
        return None

    team = context.team
    if team is None:
        team = Team.objects.get(id=context.team_id)

    return HogQLCohortQuery(cohort=cohort, team=team).get_query()


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
            inline_ast = get_cohort_subquery_or_inline(cohorts1[0][0], cohorts1[0][1], cohorts1[0][2], context)
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
            inline_ast = get_cohort_subquery_or_inline(cohorts2[0][0], cohorts2[0][1], cohorts2[0][2], context)
            if inline_ast is not None:
                return inline_ast
            return cohort_subquery(cohorts2[0][0], cohorts2[0][1], cohorts2[0][2])
        elif len(cohorts2) > 1:
            raise QueryError(f"Found multiple cohorts with name '{arg.value}'", node=arg)
        raise QueryError(f"Could not find a cohort with the name '{arg.value}'", node=arg)

    raise QueryError("cohort() takes exactly one string or integer argument", node=arg)
