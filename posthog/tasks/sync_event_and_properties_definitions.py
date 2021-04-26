# TODO: #4070 Fully temporary until these properties are migrated away from `Team` model
from typing import Any, Dict

from django.db import models
from django.dispatch.dispatcher import receiver

from posthog.celery import app
from posthog.models.event_definition import EventDefinition
from posthog.models.property_definition import PropertyDefinition
from posthog.models.team import DEFERRED_FIELDS, Team


@receiver(models.signals.post_save, sender=Team)
def team_saved(sender: Any, instance: Team, **kwargs: Dict) -> None:
    sync_event_and_properties_definitions.delay(instance.uuid)


@app.task(ignore_result=True)
def sync_event_and_properties_definitions(team_uuid: str) -> None:

    team: Team = Team.objects.only("uuid", *DEFERRED_FIELDS).get(uuid=team_uuid)

    # Transform data for quick usability
    transformed_event_usage = {
        event_usage_record["event"]: event_usage_record for event_usage_record in team.event_names_with_usage
    }
    transformed_property_usage = {
        property_usage_record["key"]: property_usage_record
        for property_usage_record in team.event_properties_with_usage
    }

    # Add or update any existing events
    for event in team.event_names:
        instance, _ = EventDefinition.objects.get_or_create(team=team, name=event)
        instance.volume_30_day = transformed_event_usage.get(event, {}).get("volume")
        instance.query_usage_30_day = transformed_event_usage.get(event, {}).get("usage_count")
        instance.save()

    # Remove any deleted events
    EventDefinition.objects.filter(team=team).exclude(name__in=team.event_names).delete()

    # Add or update any existing properties
    for property in team.event_properties:
        property_instance, _ = PropertyDefinition.objects.get_or_create(team=team, name=property)
        property_instance.volume_30_day = transformed_property_usage.get(property, {}).get("volume")
        property_instance.query_usage_30_day = transformed_property_usage.get(property, {}).get("usage_count")
        property_instance.is_numerical = property in team.event_properties_numerical
        property_instance.save()

    # Remove any deleted properties
    PropertyDefinition.objects.filter(team=team).exclude(name__in=team.event_properties).delete()
