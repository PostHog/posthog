"""Search over a project's insight alerts, in the result shape of core search.

An alert the platform holds shows its settings and state from the platform: an alert with no insight
row, and a moved alert, whose row may not follow them.
"""

from datetime import datetime
from typing import Any, Final

from django.db.models import Value
from django.utils import timezone

from posthog.helpers.full_text_search import build_rank
from posthog.models.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_cutover import insight_state_of_platform
from products.alerts.backend.platform_insight_alert import interval_of
from products.alerts_platform.backend.facade.api import search_held_configurations
from products.alerts_platform.backend.facade.contracts import HeldAlertSearchMatch, SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner

ENTITY_TYPE: Final = "alert_configuration"

_SEARCH_RANK_THRESHOLD: Final = 0.05


def search_insight_alerts(
    *,
    project_id: int,
    query: str | None,
    access_control: UserAccessControl,
    limit: int,
    with_access_levels: bool = False,
    include_count: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    rows = access_control.filter_queryset_by_access_level(
        AlertConfiguration.objects.filter(team__project_id=project_id).exclude(owner=PlatformAlertOwner.PLATFORM)
    )
    if query:
        rows = (
            rows.annotate(rank=build_rank({"name": "A"}, query, config="simple"))
            .filter(rank__gt=_SEARCH_RANK_THRESHOLD)
            .order_by("-rank", "id")
        )
    else:
        rows = rows.annotate(rank=Value(None)).order_by("name", "id")
    row_results = [
        _result(str(alert_id), name, enabled, state, calculation_interval, rank)
        for alert_id, name, enabled, state, calculation_interval, rank in rows.values_list(
            "id", "name", "enabled", "state", "calculation_interval", "rank"
        )[:limit]
    ]

    team_ids = list(Team.objects.filter(project_id=project_id).values_list("id", flat=True))
    held, held_count = search_held_configurations(
        team_ids=team_ids, source_kind=SourceKind.INSIGHT, query=query, limit=limit
    )
    now = timezone.now()
    held_results = [_held_result(match, now=now) for match in held]

    merged = [*row_results, *held_results]
    if query:
        merged.sort(key=lambda result: result["rank"], reverse=True)
    else:
        merged.sort(key=lambda result: result["extra_fields"]["name"] or "")
    results = merged[:limit]
    if with_access_levels:
        # Insight alerts carry no access control of their own.
        for result in results:
            result["user_access_level"] = None
    if not query:
        for result in results:
            result.pop("rank")
    total = rows.count() + held_count if include_count else 0
    return results, total


def _held_result(match: HeldAlertSearchMatch, *, now: datetime) -> dict[str, Any]:
    state = insight_state_of_platform(match.state, snoozed_until=match.snooze_until, at=now)
    return _result(
        str(match.public_id),
        match.name,
        match.enabled,
        state.value,
        interval_of(match.check_interval_minutes),
        match.rank,
    )


def _result(
    alert_id: str, name: str, enabled: bool, state: str, calculation_interval: str | None, rank: float | None
) -> dict[str, Any]:
    return {
        "type": ENTITY_TYPE,
        "result_id": alert_id,
        "extra_fields": {
            "name": name,
            "enabled": enabled,
            "state": state,
            "calculation_interval": calculation_interval,
        },
        "rank": rank,
    }
