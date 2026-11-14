"""Search over a project's insight alerts, in the result shape of core search.

An alert the platform holds shows its settings and state from the platform: an alert with no insight
row, and a moved alert, whose row may not follow them.
"""

from typing import Any, Final

from django.db.models import FloatField, Value
from django.utils import timezone

from posthog.helpers.full_text_search import build_rank
from posthog.models.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_cutover import insight_state_of_platform
from products.alerts.backend.platform_insight_alert import interval_of
from products.alerts_platform.backend.facade.api import runtime_by_public_id, search_held_configurations
from products.alerts_platform.backend.facade.contracts import HeldAlertSearchMatch, SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState
from products.product_analytics.backend.facade.api import viewable_insight_ids

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
    team_ids = list(Team.objects.filter(project_id=project_id).values_list("id", flat=True))
    rows = access_control.filter_queryset_by_access_level(
        AlertConfiguration.objects.filter(team_id__in=team_ids).exclude(owner=PlatformAlertOwner.PLATFORM)
    )
    if query:
        rows = (
            rows.annotate(rank=build_rank({"name": "A"}, query, config="simple"))
            .filter(rank__gt=_SEARCH_RANK_THRESHOLD)
            .order_by("-rank", "id")
        )
    else:
        rows = rows.annotate(rank=Value(None, output_field=FloatField())).order_by("name", "id")
    held = search_held_configurations(team_ids=team_ids, source_kind=SourceKind.INSIGHT, query=query)

    # An alert is readable only with its insight, as the alert API gates it.
    insight_ids = {*rows.values_list("insight_id", flat=True), *(_insight_id(match) for match in held)} - {None}
    readable_insight_ids = {
        insight_id
        for team_id in team_ids
        for insight_id in viewable_insight_ids(access_control=access_control, team_id=team_id, insight_ids=insight_ids)
    }
    rows = rows.filter(insight_id__in=readable_insight_ids)
    readable = [match for match in held if _insight_id(match) in readable_insight_ids]

    row_results = [
        _result(str(alert_id), name, enabled, state, calculation_interval, rank)
        for alert_id, name, enabled, state, calculation_interval, rank in rows.values_list(
            "id", "name", "enabled", "state", "calculation_interval", "rank"
        )[:limit]
    ]
    held_results = _held_results(readable[:limit])

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
    total = rows.count() + len(readable) if include_count else 0
    return results, total


def _insight_id(match: HeldAlertSearchMatch) -> int | None:
    insight_id = match.source_config.get("insight_id")
    return insight_id if isinstance(insight_id, int) else None


def _held_results(matches: list[HeldAlertSearchMatch]) -> list[dict[str, Any]]:
    """The results for a page of platform alerts, reading their runtime state for that page only."""
    runtime = {}
    for team_id in {match.team_id for match in matches}:
        runtime.update(
            runtime_by_public_id(
                team_id=team_id, public_ids=[match.public_id for match in matches if match.team_id == team_id]
            )
        )
    now = timezone.now()
    results = []
    for match in matches:
        alert_runtime = runtime.get(match.public_id)
        platform_state = alert_runtime.state if alert_runtime is not None else PlatformAlertState.NOT_FIRING
        state = insight_state_of_platform(platform_state, snoozed_until=match.snooze_until, at=now)
        results.append(
            _result(
                str(match.public_id),
                match.name,
                match.enabled,
                state.value,
                interval_of(match.check_interval_minutes),
                match.rank,
            )
        )
    return results


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
