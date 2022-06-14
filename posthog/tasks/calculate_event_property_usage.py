from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import DefaultDict, Dict, Tuple

from celery.app import shared_task
from django.utils import timezone

from posthog.models import Team
from posthog.models.event_definition import EventDefinition
from posthog.models.insight import Insight
from posthog.models.property_definition import PropertyDefinition


def calculate_event_property_usage() -> None:
    for team in Team.objects.all():
        calculate_event_property_usage_for_team(team_id=team.pk)


@dataclass
class EventDefinitionPayload:
    volume_30_day: int = field(default_factory=int)
    query_usage_30_day: int = field(default_factory=int)
    last_seen_at: timezone.datetime = field(default_factory=timezone.now)


@shared_task(ignore_result=True, max_retries=1)
def calculate_event_property_usage_for_team(team_id: int) -> None:
    team = Team.objects.get(pk=team_id)
    event_definition_payloads: DefaultDict[str, EventDefinitionPayload] = defaultdict(
        EventDefinitionPayload,
        {event.name: EventDefinitionPayload() for event in EventDefinition.objects.filter(team_id=team_id)},
    )
    property_insight_usage: DefaultDict[str, int] = defaultdict(
        int, {key.name: 0 for key in PropertyDefinition.objects.filter(team_id=team_id)}
    )

    since = timezone.now() - timezone.timedelta(days=30)

    for item in Insight.objects.filter(team=team, created_at__gt=since):
        for event in item.filters.get("events", []):
            event_definition_payloads[event["id"]].query_usage_30_day += 1
        for prop in item.filters.get("properties", []):
            if isinstance(prop, dict) and prop.get("key"):
                property_insight_usage[prop["key"]] += 1

    for event, (volume, last_seen_at) in _get_events_volume(team, since).items():
        event_definition_payloads[event].volume_30_day = volume
        event_definition_payloads[event].last_seen_at = last_seen_at

    for event, event_definition_payload in event_definition_payloads.items():
        EventDefinition.objects.update_or_create(name=event, team_id=team_id, defaults=asdict(event_definition_payload))

    for property_name, usage in property_insight_usage.items():
        PropertyDefinition.objects.update_or_create(
            name=property_name, team_id=team_id, defaults={"query_usage_30_day": usage or 0}
        )


def _get_events_volume(team: Team, since: timezone.datetime) -> Dict[str, Tuple[int, timezone.datetime]]:
    from posthog.client import sync_execute
    from posthog.models.event.sql import GET_EVENTS_VOLUME

    return {
        event: (volume, last_seen_at)
        for event, volume, last_seen_at in sync_execute(GET_EVENTS_VOLUME, {"team_id": team.pk, "timestamp": since})
    }
