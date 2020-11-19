from datetime import timedelta
from typing import Dict, List, Tuple

from celery.app import shared_task
from django.db import connection
from django.db.models import Count
from django.utils.timezone import now

from posthog.ee import is_ee_enabled
from posthog.models import Team
from posthog.models.dashboard_item import DashboardItem
from posthog.models.event import Event


def calculate_event_property_usage() -> None:
    for team in Team.objects.all():
        calculate_event_property_usage_for_team.delay(team_id=team.pk)


def _save_team(team: Team, event_names: Dict[str, Dict], event_properties: Dict[str, Dict]) -> None:
    def _sort(to_sort: List) -> List:
        return sorted(to_sort, key=lambda item: (item.get("usage_count", 0), item.get("volume", 0)), reverse=True)

    team.event_names_with_usage = _sort([val for _, val in event_names.items()])
    team.event_properties_with_usage = _sort([val for _, val in event_properties.items()])
    team.save()


@shared_task(ignore_result=True, max_retries=1)
def calculate_event_property_usage_for_team(team_id: int) -> None:
    team = Team.objects.get(pk=team_id)
    event_names = {event: {"event": event, "usage_count": 0} for event in team.event_names}

    event_properties = {key: {"key": key, "usage_count": 0} for key in team.event_properties}

    for item in DashboardItem.objects.filter(team=team, created_at__gt=now() - timedelta(days=30)):
        for event in item.filters.get("events", []):
            if event["id"] in event_names:
                event_names[event["id"]]["usage_count"] += 1

        for prop in item.filters.get("properties", []):
            if prop.get("key") in event_properties:
                event_properties[prop["key"]]["usage_count"] += 1

    # intermittent save in case the heavier queries don't finish
    _save_team(team, event_names, event_properties)

    events_volume = _get_events_volume(team)
    for event, value in event_names.items():
        value["volume"] = _extract_count(events_volume, event)
        event_names[event] = value

    _save_team(team, event_names, event_properties)

    properties_volume = _get_properties_volume(team)
    for key, value in event_properties.items():
        value["volume"] = _extract_count(properties_volume, key)
        event_properties[key] = value

    _save_team(team, event_names, event_properties)


def _get_properties_volume(team: Team) -> List[Tuple[str, int]]:
    timestamp = now() - timedelta(days=30)
    if is_ee_enabled():
        from ee.clickhouse.client import sync_execute
        from ee.clickhouse.sql.events import GET_PROPERTIES_VOLUME

        return sync_execute(GET_PROPERTIES_VOLUME, {"team_id": team.pk, "timestamp": timestamp},)
    cursor = connection.cursor()
    cursor.execute(
        "SELECT json_build_array(jsonb_object_keys(properties)) ->> 0 as key1, count(1) FROM posthog_event WHERE team_id = %s AND timestamp > %s group by key1 order by count desc",
        [team.pk, timestamp],
    )
    return cursor.fetchall()


def _get_events_volume(team: Team) -> List[Tuple[str, int]]:
    timestamp = now() - timedelta(days=30)
    if is_ee_enabled():
        from ee.clickhouse.client import sync_execute
        from ee.clickhouse.sql.events import GET_EVENTS_VOLUME

        return sync_execute(GET_EVENTS_VOLUME, {"team_id": team.pk, "timestamp": timestamp},)
    return (
        Event.objects.filter(team=team, timestamp__gt=timestamp)
        .values("event")
        .annotate(count=Count("id"))
        .values_list("event", "count")
    )


def _extract_count(events_volume: List[Tuple[str, int]], event: str) -> int:
    try:
        return [count[1] for count in events_volume if count[0] == event][0]
    except IndexError:
        return 0
