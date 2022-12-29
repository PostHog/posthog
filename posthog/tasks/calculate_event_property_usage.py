import json
import time
from collections import Counter
from datetime import datetime
from typing import Counter as TCounter
from typing import Dict, List, Optional, Set, Tuple

import structlog
from django.utils import timezone
from statshog.defaults.django import statsd

from posthog.celery import calculate_event_property_usage_for_team_task
from posthog.logging.timing import timed
from posthog.models import EventDefinition, EventProperty, Insight, PropertyDefinition, Team
from posthog.models.filters.filter import Filter
from posthog.models.instance_setting import get_instance_setting
from posthog.models.property.property import PropertyIdentifier
from posthog.models.property_definition import PropertyType
from posthog.queries.column_optimizer.foss_column_optimizer import FOSSColumnOptimizer
from posthog.redis import get_client

logger = structlog.get_logger(__name__)


CALCULATED_PROPERTIES_FOR_TEAMS_KEY = "CALCULATED_PROPERTIES_FOR_TEAMS_KEY"


class CountFromZero:
    def __init__(self) -> None:
        self.seen_events: Set[str] = set()
        self.seen_properties: Set[str] = set()

    def incr_event(self, event: str, current_count: int = 0) -> int:
        if event in self.seen_events:
            return current_count + 1
        else:
            self.seen_events.add(event)
            return 1

    def incr_property(self, property: str, current: Optional[int] = None, count: Optional[int] = None) -> int:
        if property in self.seen_properties:
            value_after_increment = (current or 0) + (count or 0)
            logger.info(
                "calculate_event_property_usage_for_team.incrementing_previously_seen_property",
                property=property,
                current=current,
                count=count,
                new_value=value_after_increment,
            )
            return value_after_increment
        else:
            self.seen_properties.add(property)
            value_after_increment = count or 0
            logger.info(
                "calculate_event_property_usage_for_team.incrementing_property_for_the_first_time",
                property=property,
                current=current,
                count=count,
                new_value=value_after_increment,
            )
            return value_after_increment


@timed("calculate_event_property_usage")
def calculate_event_property_usage() -> None:
    """
    We only allow one instance of calculate_event_property_usage_for_team_task to run at a time
    And we only allow teams to be processed every three hours.
    This means we can schedule a chunk of teams to be processed without causing a thundering herd,
    """

    limit: int = get_instance_setting("CALCULATE_EVENT_PROPERTY_USAGE_LIMIT")

    now_in_seconds_since_epoch = time.time()
    three_hours_ago = now_in_seconds_since_epoch - (3600 * 3)
    teams_to_exclude = recently_calculated_teams(
        now_in_seconds_since_epoch=now_in_seconds_since_epoch, limit_seconds=three_hours_ago
    )
    next_teams = Team.objects.exclude(id__in=teams_to_exclude).values_list("id", flat=True)[:limit]
    for team in next_teams:
        calculate_event_property_usage_for_team_task.delay(team_id=team)
        get_client().zadd(name=CALCULATED_PROPERTIES_FOR_TEAMS_KEY, mapping={str(team): time.time()})


def recently_calculated_teams(now_in_seconds_since_epoch: float, limit_seconds: float) -> Set[int]:
    """
    Each time a team has properties calculated it is added to the sorted set with the seconds since epoch as its score.
    That means we can read all teams in that set whose score is within the seconds since epoch covered in the last
    limit_seconds and exclude them from recalculation
    """

    return {
        int(team_id)
        for team_id, _ in get_client().zrange(
            name=CALCULATED_PROPERTIES_FOR_TEAMS_KEY,
            start=int(limit_seconds),
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
        count_from_zero = CountFromZero()
        altered_events: Set[str] = set()
        altered_properties: Set[str] = set()

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
                altered_properties.add(property_key)

        insight_series_events, counted_properties = _get_insight_query_usage(team_id, since)

        for series_event in insight_series_events:
            if series_event not in event_definitions:
                logger.info(
                    "calculate_event_property_usage_for_team.insight_uses_event_with_no_definition",
                    team=team_id,
                    event_id=series_event,
                )
                continue
            event_definition = event_definitions[series_event]
            event_definition.query_usage_30_day = count_from_zero.incr_event(
                event_definition.name, event_definition.query_usage_30_day
            )

        for counted_property in counted_properties:
            property_name, _, _ = counted_property
            count_for_property = counted_properties[counted_property]

            if property_name not in property_definitions:
                logger.info(
                    "calculate_event_property_usage_for_team.insight_uses_property_with_no_definition",
                    team=team_id,
                    property=property_name,
                )
                continue
            property_definition = property_definitions[property_name]
            property_definition.query_usage_30_day = count_from_zero.incr_property(
                property_definition.name, property_definition.query_usage_30_day, count_for_property
            )

        events_volume = _get_events_volume(team_id, since)
        for event, (volume, last_seen_at) in events_volume.items():
            if event not in event_definitions:
                logger.info(
                    "calculate_event_property_usage_for_team.event_volume_found_for_event_with_no_definition",
                    team_id=team_id,
                    event_name=event,
                )
                continue
            event_definitions[event].volume_30_day = volume
            event_definitions[event].last_seen_at = last_seen_at
            altered_events.add(event)

        altered_events.update(count_from_zero.seen_events)
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
            fields=["volume_30_day", "query_usage_30_day", "last_seen_at"],
            batch_size=1000,
        )

        altered_properties.update(count_from_zero.seen_properties)
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
            fields=["property_type", "query_usage_30_day", "is_numerical"],
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


def _get_insight_query_usage(team_id: int, since: datetime) -> Tuple[List[str], TCounter[PropertyIdentifier]]:
    event_usage: List[str] = []
    counted_properties: TCounter[PropertyIdentifier] = Counter()

    insight_filters = [
        (id, Filter(data=filters) if filters else None)
        for (id, filters) in Insight.objects.filter(team__id=team_id, created_at__gt=since)
        .values_list("id", "filters")
        .all()
    ]

    statsd.gauge(
        "calculate_event_property_usage_for_team.insight_filters_to_process",
        value=len(insight_filters),
        tags={"team": team_id},
    )

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

        for item_filter_action in item_filters.actions:
            action = item_filter_action.get_action()
            event_usage.extend(action.get_step_events())

        event_properties = FOSSColumnOptimizer(item_filters, team_id).used_properties_with_type("event")
        counted_properties.update(event_properties)

    statsd.gauge(
        "calculate_event_property_usage_for_team.counted_events_for_team_insights",
        value=len(event_usage),
        tags={"team": team_id},
    )
    statsd.gauge(
        "calculate_event_property_usage_for_team.counted_properties_for_team_insights",
        value=sum(counted_properties.values()),
        tags={"team": team_id},
    )

    return event_usage, counted_properties
