import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import structlog
from django.db.models import Sum
from django.utils import timezone

from posthog.internal_metrics import incr
from posthog.logging.timing import timed
from posthog.models import EventDefinition, EventProperty, Insight, PropertyDefinition, Team
from posthog.models.filters.filter import Filter
from posthog.models.property_definition import PropertyType
from posthog.redis import get_client

logger = structlog.get_logger(__name__)


CALCULATED_PROPERTIES_FOR_TEAMS_KEY = "CALCULATED_PROPERTIES_FOR_TEAMS_KEY"


class CountFromZero:
    def __init__(self) -> None:
        self.seen_events: Set[str] = set()
        self.seen_properties: Set[str] = set()

    def incr_event(self, event: EventDefinition) -> int:
        if event.name in self.seen_events:
            return event.query_usage_30_day + 1
        else:
            self.seen_events.add(event.name)
            return 1

    def incr_property(self, property: PropertyDefinition) -> int:
        if property.name in self.seen_properties:
            return property.query_usage_30_day + 1
        else:
            self.seen_properties.add(property.name)
            return 1


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


def gauge_event_property_usage() -> None:
    from posthog.internal_metrics import gauge

    event_query_usage_30_day_sum: int = EventDefinition.objects.aggregate(sum=Sum("query_usage_30_day"))["sum"]
    event_volume_30_day_sum: int = EventDefinition.objects.aggregate(sum=Sum("volume_30_day"))["sum"]
    property_query_usage_30_day_sum: int = PropertyDefinition.objects.aggregate(sum=Sum("query_usage_30_day"))["sum"]
    property_volume_30_day_sum: int = PropertyDefinition.objects.aggregate(sum=Sum("volume_30_day"))["sum"]

    gauge("calculate_event_property_usage.event_query_usage_30_day_sum", value=event_query_usage_30_day_sum or 0)
    gauge("calculate_event_property_usage.event_volume_30_day_sum", value=event_volume_30_day_sum or 0)
    gauge("calculate_event_property_usage.property_query_usage_30_day_sum", value=property_query_usage_30_day_sum or 0)
    gauge("calculate_event_property_usage.property_volume_30_day_sum", value=property_volume_30_day_sum or 0)


@timed("calculate_event_property_usage_for_team")
def calculate_event_property_usage_for_team(team_id: int, *, complete_inference: bool = False) -> None:
    """Calculate Data Management stats for a specific team.

    The complete_inference flag enables much more extensive inference of event/actor taxonomy based on ClickHouse data.
    This is not needed in production - where the plugin server is responsible for this - but in the demo environment
    data comes preloaded, necessitating complete inference."""

    try:
        count_from_zero = CountFromZero()

        event_definitions: Dict[str, EventDefinition] = {
            known_event.name: known_event for known_event in EventDefinition.objects.filter(team_id=team_id)
        }

        property_definitions: Dict[str, PropertyDefinition] = {
            known_property.name: known_property for known_property in PropertyDefinition.objects.filter(team_id=team_id)
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

        insight_series_events, insight_properties = _get_insight_query_usage(team_id, since)

        for series_event in insight_series_events:
            if series_event not in event_definitions:
                logger.info(
                    "calculate_event_property_usage_for_team.insight_uses_event_with_no_definition",
                    team=team_id,
                    event_id=series_event,
                )
                continue
            event_definition = event_definitions[series_event]
            event_definition.query_usage_30_day = count_from_zero.incr_event(event_definition)

        for property in insight_properties:
            if property not in property_definitions:
                logger.info(
                    "calculate_event_property_usage_for_team.insight_uses_property_with_no_definition",
                    team=team_id,
                    property=property,
                )
                continue
            property_definition = property_definitions[property]
            property_definition.query_usage_30_day = count_from_zero.incr_property(property_definition)

        events_volume = _get_events_volume(team_id, since)
        for event, (volume, last_seen_at) in events_volume.items():
            event_definitions[event].volume_30_day = volume
            event_definitions[event].last_seen_at = last_seen_at

        EventDefinition.objects.bulk_update(
            event_definitions.values(), fields=["volume_30_day", "query_usage_30_day", "last_seen_at"], batch_size=5000
        )

        PropertyDefinition.objects.bulk_update(
            property_definitions.values(),
            fields=["property_type", "query_usage_30_day", "is_numerical"],
            batch_size=5000,
        )

        incr("calculate_event_property_usage_for_team_success", tags={"team": team_id})
    except Exception as exc:
        logger.error("calculate_event_property_usage_for_team.failed", team=team_id, exc=exc, exc_info=True)
        incr("calculate_event_property_usage_for_team_failure", tags={"team": team_id})
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


def _get_insight_query_usage(team_id: int, since: datetime) -> Tuple[List[str], List[str]]:
    event_usage: List[str] = []
    property_usage: List[str] = []

    insight_filters = [
        (id, Filter(data=filters) if filters else None)
        for (id, filters) in Insight.objects.filter(team__id=team_id, created_at__gt=since)
        .values_list("id", "filters")
        .all()
    ]
    for id, item_filters in insight_filters:
        if item_filters is None:
            logger.info(
                "calculate_event_property_usage_for_team.insight_has_no_filters",
                team=team_id,
                insight_id=id,
            )
            continue

        for item_filter_event in item_filters.events:
            event_usage.append(str(item_filter_event.id))
            property_usage.extend([p.key for p in item_filter_event.property_groups.flat])

        property_usage.extend([p.key for p in item_filters.property_groups.flat])

        # todo are there more usages of properties? e.g. math aggregations?

    return event_usage, property_usage
