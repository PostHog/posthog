import json
import time
from typing import Dict, List, Optional, Set, Tuple

import structlog
from django.utils import timezone
from statshog.defaults.django import statsd

from posthog.logging.timing import timed
from posthog.models import EventDefinition, EventProperty, PropertyDefinition, Team
from posthog.models.property_definition import PropertyType
from posthog.redis import get_client

logger = structlog.get_logger(__name__)


CALCULATED_PROPERTIES_FOR_TEAMS_KEY = "CALCULATED_PROPERTIES_FOR_TEAMS_KEY"


@timed("calculate_event_property_usage")
def calculate_event_property_usage() -> None:
    teams_to_exclude = recently_calculated_teams(now_in_seconds_since_epoch=time.time())

    for team_id in Team.objects.values_list("id", flat=True):
        if team_id not in teams_to_exclude:
            calculate_event_property_usage_for_team(team_id=team_id)
            get_client().zadd(name=CALCULATED_PROPERTIES_FOR_TEAMS_KEY, mapping={str(team_id): time.time()})


def recently_calculated_teams(now_in_seconds_since_epoch: float) -> Set[int]:
    """
    Each time a team has properties calculated it is added to the sorted set with the seconds since epoch as its score.
    That means we can read all teams in that set whose score is within the seconds since epoch covered in the last 24 hours
    And exclude them from recalculation
    """
    one_day_ago = now_in_seconds_since_epoch - 86400
    return {
        int(team_id)
        for team_id, _ in get_client().zrange(
            name=CALCULATED_PROPERTIES_FOR_TEAMS_KEY,
            start=int(one_day_ago),
            end=int(now_in_seconds_since_epoch),
            withscores=True,
            byscore=True,
        )
    }


@timed("calculate_event_property_usage_for_team")
def calculate_event_property_usage_for_team(team_id: int, *, complete_inference: bool = False) -> None:
    """Calculate Data Management stats for a specific team.

    The complete_inference flag enables much more extensive inference of event/actor taxonomy based on ClickHouse data.
    This is not needed in production - where the plugin server is responsible for this - but in the demo environment
    data comes preloaded, necessitating complete inference."""

    try:
        # django orm doesn't track if a model has been changed
        # between count from zero and these two sets we manually track which models have changed
        altered_events: Set[str] = set()
        altered_properties: Set[str] = set()

        event_definitions: Dict[str, EventDefinition] = {
            known_event.name: known_event for known_event in EventDefinition.objects.filter(team_id=team_id)
        }

        property_definitions: Dict[str, PropertyDefinition] = {
            known_property.name: known_property
            for known_property in PropertyDefinition.objects.filter(team_id=team_id, type=PropertyDefinition.Type.EVENT)
        }

        since = timezone.now() - timezone.timedelta(days=30)

        if complete_inference:
            # Infer (event, property) pairs
            event_properties = _get_event_properties(team_id, since)
            EventProperty.objects.bulk_create(
                [
                    EventProperty(team_id=team_id, event=event, property=property_key)
                    for event, property_key in event_properties
                ],
                ignore_conflicts=True,
            )

            for event, _ in event_properties:
                if event not in event_definitions:
                    event_definitions[event] = EventDefinition.objects.create(team_id=team_id, name=event)

            # Infer property types
            property_types = _get_property_types(team_id, since)
            for property_key, property_type in property_types.items():
                if property_key not in property_definitions:
                    property_definitions[property_key] = PropertyDefinition.objects.create(
                        team_id=team_id, name=property_key
                    )
                if property_definitions[property_key].property_type is not None:
                    continue  # Don't override property type if it's already set

                property_definitions[property_key].property_type = property_type
                property_definitions[property_key].is_numerical = property_type == PropertyType.Numeric
                altered_properties.add(property_key)

        events_volume = _get_events_volume(team_id, since)
        for event, (volume, last_seen_at) in events_volume.items():
            if event not in event_definitions:
                logger.warn(
                    "calculate_event_property_usage_for_team.event_volume_found_for_event_with_no_definition",
                    team_id=team_id,
                    event_name=event,
                )
                continue
            event_definitions[event].volume_30_day = volume
            event_definitions[event].last_seen_at = last_seen_at
            altered_events.add(event)

        statsd.gauge(
            "calculate_event_property_usage_for_team.events_to_update",
            value=len(altered_events),
            tags={"team": team_id},
        )
        EventDefinition.objects.bulk_update(
            [
                event_definition
                for event_definition in event_definitions.values()
                if event_definition.name in altered_events
            ],
            fields=["volume_30_day", "last_seen_at"],
            batch_size=1000,
        )

        statsd.gauge(
            "calculate_event_property_usage_for_team.event_properties_to_update",
            value=len(altered_properties),
            tags={"team": team_id},
        )
        PropertyDefinition.objects.bulk_update(
            [
                property_definition
                for property_definition in property_definitions.values()
                if property_definition.name in altered_properties
            ],
            fields=["property_type", "is_numerical"],
            batch_size=1000,
        )

        statsd.incr("calculate_event_property_usage_for_team_success", tags={"team": team_id})
    except Exception as exc:
        logger.error("calculate_event_property_usage_for_team.failed", team=team_id, exc=exc, exc_info=True)
        statsd.incr("calculate_event_property_usage_for_team_failure", tags={"team": team_id})
        raise exc


def _get_events_volume(team_id: int, since: timezone.datetime) -> Dict[str, Tuple[int, timezone.datetime]]:
    from posthog.client import sync_execute
    from posthog.models.event.sql import GET_EVENTS_VOLUME

    return {
        event: (volume, last_seen_at)
        for event, volume, last_seen_at in sync_execute(GET_EVENTS_VOLUME, {"team_id": team_id, "timestamp": since})
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


def _get_property_types(team_id: int, since: timezone.datetime) -> Dict[str, Optional[PropertyType]]:
    """Determine property types based on ClickHouse data."""
    from posthog.client import sync_execute
    from posthog.models.event.sql import GET_EVENT_PROPERTY_SAMPLE_JSON_VALUES
    from posthog.models.group.sql import GET_GROUP_PROPERTY_SAMPLE_JSON_VALUES
    from posthog.models.person.sql import GET_PERSON_PROPERTY_SAMPLE_JSON_VALUES

    property_types = {
        property_key: _infer_property_type(sample_json_value)
        for property_key, sample_json_value in sync_execute(
            GET_EVENT_PROPERTY_SAMPLE_JSON_VALUES, {"team_id": team_id, "timestamp": since}
        )
    }

    for property_key, sample_json_value in sync_execute(GET_PERSON_PROPERTY_SAMPLE_JSON_VALUES, {"team_id": team_id}):
        if property_key not in property_types:
            property_types[property_key] = _infer_property_type(sample_json_value)
    for property_key, sample_json_value in sync_execute(GET_GROUP_PROPERTY_SAMPLE_JSON_VALUES, {"team_id": team_id}):
        if property_key not in property_types:
            property_types[property_key] = _infer_property_type(sample_json_value)

    return property_types


def _get_event_properties(team_id: int, since: timezone.datetime) -> List[Tuple[str, str]]:
    """Determine which properties have been since with which events based on ClickHouse data."""
    from posthog.client import sync_execute
    from posthog.models.event.sql import GET_EVENT_PROPERTIES

    return sync_execute(GET_EVENT_PROPERTIES, {"team_id": team_id, "timestamp": since})
