from datetime import timedelta
from typing import List, Tuple

from celery.app import shared_task
from django.db.models import Count
from django.utils.timezone import now

from posthog.models import Team
from posthog.models.event import Event
from posthog.models.event_definition import EventDefinition
from posthog.models.insight import Insight
from posthog.models.property_definition import PropertyDefinition
from posthog.utils import is_clickhouse_enabled


def calculate_event_property_usage() -> None:
    for team in Team.objects.all():
        calculate_event_property_usage_for_team(team_id=team.pk)


@shared_task(ignore_result=True, max_retries=1)
def calculate_event_property_usage_for_team(team_id: int) -> None:
    team = Team.objects.get(pk=team_id)
    event_names = {event.name: 0 for event in EventDefinition.objects.filter(team_id=team_id)}

    event_properties = {key.name: 0 for key in PropertyDefinition.objects.filter(team_id=team_id)}

    for item in Insight.objects.filter(team=team, created_at__gt=now() - timedelta(days=30)):
        for event in item.filters.get("events", []):
            if event["id"] in event_names:
                event_names[event["id"]] += 1

        for prop in item.filters.get("properties", []):
            if isinstance(prop, dict) and prop.get("key") in event_properties:
                event_properties[prop["key"]] += 1

    events_volume = _get_events_volume(team)
    for event, value in event_names.items():
        volume = _extract_count(events_volume, event)
        EventDefinition.objects.filter(name=event, team_id=team_id).update(
            volume_30_day=volume, query_usage_30_day=value
        )

    for key, value in event_properties.items():
        PropertyDefinition.objects.filter(name=key, team_id=team_id).update(query_usage_30_day=value)


def _get_events_volume(team: Team) -> List[Tuple[str, int]]:
    timestamp = now() - timedelta(days=30)
    if is_clickhouse_enabled():
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
