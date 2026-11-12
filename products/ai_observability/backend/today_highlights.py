from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from django.utils import timezone

from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.ai_observability.backend.models.evaluation_reports import EvaluationReportRun
from products.ai_observability.backend.models.evaluations import Evaluation
from products.today.backend.facade.contracts import (
    HighlightContext,
    HighlightFindings,
    HighlightMetric,
    HighlightValueFormat,
)
from products.today.backend.facade.enums import HighlightMetricReason, HighlightUnit
from products.today.backend.facade.highlight_helpers import short

NUMBER_PREFIX = "evaluation:"
NUMBER_CANDIDATES = 3
SERIES_RUNS = 8
FRESH_DAYS = 30
PERCENT = HighlightValueFormat(format="percentage", prefix=None, postfix=None, decimal_places=None)


def _pass_rates(evaluation_id: UUID) -> list[tuple[datetime, float]]:
    runs = (
        EvaluationReportRun.objects.filter(report__evaluation_id=evaluation_id, report__deleted=False)
        .order_by("-period_end")
        .values_list("period_end", "metadata")[:SERIES_RUNS]
    )
    rates = []
    for period_end, metadata in runs:
        rate = (metadata or {}).get("pass_rate")
        if isinstance(rate, int | float):
            rates.append((period_end, float(rate)))
    return rates[::-1]


def _number(context: HighlightContext, evaluation_id: UUID, name: str) -> HighlightMetric | None:
    rates = _pass_rates(evaluation_id)
    if not rates or rates[-1][0] < timezone.now() - timedelta(days=FRESH_DAYS):
        return None
    value = rates[-1][1]
    previous = rates[-2][1] if len(rates) > 1 else None
    return HighlightMetric(
        key=f"{NUMBER_PREFIX}{evaluation_id}",
        name=short(name, 60),
        value=value,
        unit=HighlightUnit.NUMBER,
        change_pct=(value - previous) / previous * 100 if previous else None,
        series=[rate for _end, rate in rates],
        url=f"/ai-evals/evaluations/{evaluation_id}",
        value_format=PERCENT,
        period_starts=[timezone.localtime(end, context.team.timezone_info).date() for end, _rate in rates],
        reason=HighlightMetricReason.EVALUATION,
        previous_value=previous,
    )


def find_evaluation_number(context: HighlightContext) -> HighlightFindings:
    evaluations = (
        Evaluation.objects.filter(
            team_id=context.team.id,
            created_by_id=context.user.id,
            enabled=True,
            deleted=False,
            reports__deleted=False,
        )
        .order_by("-created_at")
        .values_list("id", "name")
        .distinct()[:NUMBER_CANDIDATES]
    )
    for evaluation_id, name in evaluations:
        if f"{NUMBER_PREFIX}{evaluation_id}" in context.hidden:
            continue
        number = _number(context, evaluation_id, name)
        if number is not None:
            return HighlightFindings(pulse=(number,))
    return HighlightFindings()


def _ids(keys: Sequence[str]) -> set[UUID]:
    ids: set[UUID] = set()
    for key in keys:
        if key.startswith(NUMBER_PREFIX):
            try:
                ids.add(UUID(key.removeprefix(NUMBER_PREFIX)))
            except ValueError:
                continue
    return ids


def name_evaluation_numbers(team: Team, user: User, keys: list[str]) -> dict[str, str]:
    ids = _ids(keys)
    if not ids:
        return {}
    rows = list(
        Evaluation.objects.filter(team_id=team.id, id__in=ids, deleted=False).values_list(
            "id", "name", "team_id", "created_by_id"
        )
    )
    denied = set(
        UserAccessControl(user=user, team=team, organization_id=str(team.organization_id)).denied_object_ids(
            "evaluation", ((str(id), team_id, created_by_id) for id, _name, team_id, created_by_id in rows), "viewer"
        )
    )
    return {f"{NUMBER_PREFIX}{id}": short(name, 60) for id, name, _team_id, _created in rows if str(id) not in denied}
