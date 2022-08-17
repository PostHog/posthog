import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import DefaultDict, Dict, Optional, Tuple

from celery.app import shared_task
from django.utils import timezone

from posthog.models import Team
from posthog.models.insight import Insight

from ..models.property_definition import PropertyType

try:
    from ee.models.event_definition import EnterpriseEventDefinition as EventDefinition
    from ee.models.property_definition import EnterprisePropertyDefinition as PropertyDefinition
except ImportError:
    from posthog.models.event_definition import EventDefinition
    from posthog.models.property_definition import PropertyDefinition


def calculate_event_property_usage() -> None:
    for team in Team.objects.all():
        calculate_event_property_usage_for_team(team_id=team.pk)


@dataclass
class EventDefinitionPayload:
    volume_30_day: int = field(default_factory=int)
    query_usage_30_day: int = field(default_factory=int)
    last_seen_at: timezone.datetime = field(default_factory=timezone.now)


@dataclass
class PropertyDefinitionPayload:
    property_type: Optional[PropertyType] = field(default=None)
    query_usage_30_day: int = field(default_factory=int)


@shared_task(ignore_result=True, max_retries=1)
def calculate_event_property_usage_for_team(team_id: int) -> None:
    team = Team.objects.get(pk=team_id)
    event_definition_payloads: DefaultDict[str, EventDefinitionPayload] = defaultdict(
        EventDefinitionPayload,
        {event.name: EventDefinitionPayload() for event in EventDefinition.objects.filter(team_id=team_id)},
    )
    property_definition_payloads: DefaultDict[str, PropertyDefinitionPayload] = defaultdict(
        PropertyDefinitionPayload,
        {key.name: PropertyDefinitionPayload() for key in PropertyDefinition.objects.filter(team_id=team_id)},
    )

    since = timezone.now() - timezone.timedelta(days=30)

    for item in Insight.objects.filter(team=team, created_at__gt=since):
        for event in item.filters.get("events", []):
            event_definition_payloads[event["id"]].query_usage_30_day += 1
        for prop in item.filters.get("properties", []):
            if isinstance(prop, dict) and prop.get("key"):
                property_definition_payloads[prop["key"]].query_usage_30_day += 1

    events_volume = _get_events_volume(team, since)
    for event, (volume, last_seen_at) in events_volume.items():
        event_definition_payloads[event].volume_30_day = volume
        event_definition_payloads[event].last_seen_at = last_seen_at

    property_types = _get_property_types(team, since)
    for property_key, property_type in property_types.items():
        property_definition_payloads[property_key].property_type = property_type

    for event, event_definition_payload in event_definition_payloads.items():
        EventDefinition.objects.update_or_create(name=event, team_id=team_id, defaults=asdict(event_definition_payload))

    for property_key, property_definition_payload in property_definition_payloads.items():
        PropertyDefinition.objects.update_or_create(
            name=property_key,
            team_id=team_id,
            defaults={
                **asdict(property_definition_payload),
                "is_numerical": property_definition_payload.property_type == PropertyType.Numeric,
            },
        )


def _get_events_volume(team: Team, since: timezone.datetime) -> Dict[str, Tuple[int, timezone.datetime]]:
    from posthog.client import sync_execute
    from posthog.models.event.sql import GET_EVENTS_VOLUME

    return {
        event: (volume, last_seen_at)
        for event, volume, last_seen_at in sync_execute(GET_EVENTS_VOLUME, {"team_id": team.pk, "timestamp": since})
    }


def _infer_property_type(sample_json_value: str) -> Optional[PropertyType]:
    parsed_value = json.loads(sample_json_value)
    if isinstance(parsed_value, (float, int)):
        return PropertyType.Numeric
    if isinstance(parsed_value, bool):
        return PropertyType.Boolean
    if isinstance(parsed_value, str):
        return PropertyType.String
    return None


def _get_property_types(team: Team, since: timezone.datetime) -> Dict[str, Optional[PropertyType]]:
    from posthog.client import sync_execute
    from posthog.models.event.sql import GET_EVENT_PROPERTY_SAMPLE_JSON_VALUES

    return {
        property_key: _infer_property_type(sample_json_value)
        for property_key, sample_json_value in sync_execute(
            GET_EVENT_PROPERTY_SAMPLE_JSON_VALUES, {"team_id": team.pk, "timestamp": since}
        )
    }
