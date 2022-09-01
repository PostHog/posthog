import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import DefaultDict, Dict, List, Optional, Tuple, cast

from celery.app import shared_task
from django.utils import timezone

from posthog.logging.timing import timed
from posthog.models import EventDefinition, EventProperty, Insight, PropertyDefinition, Team
from posthog.models.property_definition import PropertyType


@timed("calculate_event_property_usage")
def calculate_event_property_usage() -> None:
    for team in Team.objects.all():
        calculate_event_property_usage_for_team(team_id=team.pk)


@dataclass
class _EventDefinitionPayload:
    volume_30_day: int = field(default_factory=int)
    query_usage_30_day: int = field(default_factory=int)
    last_seen_at: timezone.datetime = field(default_factory=timezone.now)


@dataclass
class _PropertyDefinitionPayload:
    property_type: Optional[PropertyType] = field(default=None)
    query_usage_30_day: int = field(default_factory=int)


@shared_task(ignore_result=True, max_retries=1)
def calculate_event_property_usage_for_team(team_id: int, *, complete_inference: bool = False) -> None:
    """Calculate Data Management stats for a specific team.

    The complete_inference flag enables much more extensive inference of event/actor taxonomy based on ClickHouse data.
    This is not needed in production - where the plugin server is responsible for this - but in the demo environment
    data comes preloaded, necessitating complete inference."""
    import structlog

    logger = structlog.get_logger(__name__)
    from posthog.internal_metrics import incr

    try:
        team = Team.objects.get(pk=team_id)

        # Prepare update payloads
        event_definition_payloads: DefaultDict[str, _EventDefinitionPayload] = defaultdict(
            _EventDefinitionPayload,
            {
                known_event.name: _EventDefinitionPayload()
                for known_event in EventDefinition.objects.filter(team_id=team_id)
            },
        )
        property_definition_payloads: DefaultDict[str, _PropertyDefinitionPayload] = defaultdict(
            _PropertyDefinitionPayload,
            {
                known_property.name: _PropertyDefinitionPayload(
                    property_type=cast(PropertyType, known_property.property_type)
                    or (PropertyType.Numeric if known_property.is_numerical else None)
                )
                for known_property in PropertyDefinition.objects.filter(team_id=team_id)
            },
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

        if complete_inference:
            # Infer (event, property) pairs
            event_properties = _get_event_properties(team, since)
            EventProperty.objects.bulk_create(
                [
                    EventProperty(team_id=team_id, event=event, property=property_key)
                    for event, property_key in event_properties
                ],
                ignore_conflicts=True,
            )
            # Infer property types
            property_types = _get_property_types(team, since)
            for property_key, property_type in property_types.items():
                if property_definition_payloads[property_key].property_type is not None:
                    continue  # Don't override property type if it's already set
                property_definition_payloads[property_key].property_type = property_type

        # Update event definitions
        for event, event_definition_payload in event_definition_payloads.items():
            # TODO: Use Django 4.1's bulk_create() with update_conflicts=True
            EventDefinition.objects.update_or_create(
                name=event, team_id=team_id, defaults=asdict(event_definition_payload)
            )

        # Update property definitions
        for property_key, property_definition_payload in property_definition_payloads.items():
            # TODO: Use Django 4.1's bulk_create() with update_conflicts=True
            PropertyDefinition.objects.update_or_create(
                name=property_key,
                team_id=team_id,
                defaults={
                    **asdict(property_definition_payload),
                    "is_numerical": property_definition_payload.property_type == PropertyType.Numeric,
                },
            )
        incr("calculate_event_property_usage_for_team_success", tags={"team": team_id})
    except Exception as exc:
        logger.error("calculate_event_property_usage_for_team.failed", team=team_id, exc=exc, exc_info=True)
        incr("calculate_event_property_usage_for_team_failure", tags={"team": team_id})
        raise exc


def _get_events_volume(team: Team, since: timezone.datetime) -> Dict[str, Tuple[int, timezone.datetime]]:
    from posthog.client import sync_execute
    from posthog.models.event.sql import GET_EVENTS_VOLUME

    return {
        event: (volume, last_seen_at)
        for event, volume, last_seen_at in sync_execute(GET_EVENTS_VOLUME, {"team_id": team.pk, "timestamp": since})
    }


def _infer_property_type(sample_json_value: str) -> Optional[PropertyType]:
    """Parse the provided sample value as JSON and return its property type."""
    parsed_value = json.loads(sample_json_value)
    if isinstance(parsed_value, bool):
        return PropertyType.Boolean
    if isinstance(parsed_value, (float, int)):
        return PropertyType.Numeric
    if isinstance(parsed_value, str):
        return PropertyType.String
    return None


def _get_property_types(team: Team, since: timezone.datetime) -> Dict[str, Optional[PropertyType]]:
    """Determine property types based on ClickHouse data."""
    from posthog.client import sync_execute
    from posthog.models.event.sql import GET_EVENT_PROPERTY_SAMPLE_JSON_VALUES
    from posthog.models.group.sql import GET_GROUP_PROPERTY_SAMPLE_JSON_VALUES
    from posthog.models.person.sql import GET_PERSON_PROPERTY_SAMPLE_JSON_VALUES

    property_types = {
        property_key: _infer_property_type(sample_json_value)
        for property_key, sample_json_value in sync_execute(
            GET_EVENT_PROPERTY_SAMPLE_JSON_VALUES, {"team_id": team.pk, "timestamp": since}
        )
    }

    for property_key, sample_json_value in sync_execute(GET_PERSON_PROPERTY_SAMPLE_JSON_VALUES, {"team_id": team.pk}):
        if property_key not in property_types:
            property_types[property_key] = _infer_property_type(sample_json_value)
    for property_key, sample_json_value in sync_execute(GET_GROUP_PROPERTY_SAMPLE_JSON_VALUES, {"team_id": team.pk}):
        if property_key not in property_types:
            property_types[property_key] = _infer_property_type(sample_json_value)

    return property_types


def _get_event_properties(team: Team, since: timezone.datetime) -> List[Tuple[str, str]]:
    """Determine which properties have been since with which events based on ClickHouse data."""
    from posthog.client import sync_execute
    from posthog.models.event.sql import GET_EVENT_PROPERTIES

    return sync_execute(GET_EVENT_PROPERTIES, {"team_id": team.pk, "timestamp": since})
