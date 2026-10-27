from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from rest_framework.exceptions import ValidationError

from posthog.clickhouse.query_tagging import Feature, Product, tags_context

from products.product_analytics.backend.facade.api import get_insight_series, saved_insight_for_read
from products.product_analytics.backend.facade.measurement import insight_delivery_evidence

from ..facade.contracts import Metric

if TYPE_CHECKING:
    from posthog.models import Team, User

    from products.product_analytics.backend.facade.contracts import InsightSeries


def _insight_series(team: Team, user: User, short_id: str, *, force_refresh: bool = False) -> InsightSeries | None:
    with tags_context(product=Product.BETS, feature=Feature.QUERY, team_id=team.id, user_id=user.id):
        return get_insight_series(
            team=team,
            user=user,
            short_id=short_id,
            use_saved_date_range=True,
            blocking=force_refresh,
            force_refresh=force_refresh,
        )


def refresh_metrics(team: Team, user: User, insight_ids: Sequence[str]) -> None:
    for short_id in dict.fromkeys(insight_ids):
        if short_id:
            _insight_series(team, user, short_id, force_refresh=True)


def metric(team: Team, user: User, short_id: str) -> Metric:
    if short_id:
        result = _insight_series(team, user, short_id)
        if result is None:
            insight = saved_insight_for_read(team=team, user=user, short_id=short_id)
            return Metric(
                name=insight.name if insight and insight.name else "Goal",
                values=[],
                dates=[],
                current=None,
                change=None,
                message="Waiting for insight data.",
            )
        if len(result.series) != 1:
            return Metric(
                name=result.name or "Goal",
                values=[],
                dates=[],
                current=None,
                change=None,
                message="Choose an insight with a single series for this goal.",
            )
        points = next(iter(result.series.values()))
        values = [float(value) for _, value in points if math.isfinite(value)]
        dates = [day.isoformat() for day, value in points if math.isfinite(value)]
        name = result.name or "Goal"
        unit = result.value_postfix or ""
        if values and 0 in values and result.averaged_series:
            with tags_context(product=Product.BETS, feature=Feature.QUERY, team_id=team.id, user_id=user.id):
                delivery = insight_delivery_evidence(team=team, user=user, short_id=short_id)
            first_observed_day = (
                delivery.first_event_at.astimezone(ZoneInfo(team.timezone)).date()
                if delivery and delivery.first_event_at
                else None
            )
            last_observed_day = (
                delivery.last_event_at.astimezone(ZoneInfo(team.timezone)).date()
                if delivery and delivery.last_event_at
                else None
            )
            observed = [
                (day.isoformat(), float(value))
                for day, value in points
                if first_observed_day
                and last_observed_day
                and first_observed_day <= day <= last_observed_day
                and math.isfinite(value)
            ]
            values = [value for _, value in observed]
            dates = [day for day, _ in observed]
            if not delivery or not delivery.events or last_observed_day is None or last_observed_day < points[-1][0]:
                return Metric(
                    name=name,
                    values=values,
                    dates=dates,
                    current=None,
                    change=None,
                    message="Waiting for observations in the current measurement period.",
                    unit=unit,
                )
    else:
        return Metric(
            name="Goal",
            values=[],
            dates=[],
            current=None,
            change=None,
            message="Connect a saved insight to measure this goal.",
        )
    current = values[-1] if values else None
    change = ((values[-1] - values[0]) / abs(values[0]) * 100) if len(values) > 1 and values[0] else None
    return Metric(
        name=name,
        values=values,
        dates=dates,
        current=current,
        change=change,
        message="" if values else "No data yet.",
        unit=unit,
    )


def validate_goal(team: Team, user: User, short_id: str) -> None:
    if not short_id:
        return
    if saved_insight_for_read(team=team, user=user, short_id=short_id) is None:
        raise ValidationError({"goal_insight": "Choose a saved insight you can view in this project."})
    result = _insight_series(team, user, short_id)
    if result is not None and len(result.series) != 1:
        raise ValidationError({"goal_insight": "Choose a saved insight with one series."})
