from django.core.exceptions import ValidationError
from django.db import models

from posthog.schema import CoreEvent

from posthog.models.team import Team


def validate_core_event(event: dict) -> None:
    """Validate a single core event using the schema's CoreEvent model."""

    try:
        CoreEvent.model_validate(event)
    except Exception as e:
        raise ValidationError(f"Invalid core event: {e}")

    # Prevent "all events" - EventsNode must have a specific event name
    filter_data = event.get("filter", {})
    if filter_data.get("kind") == "EventsNode":
        event_name = filter_data.get("event")
        if not event_name:
            raise ValidationError("Core event cannot use 'All events'. Please select a specific event.")


# Intentionally not inheriting from UUIDModel because we're using a OneToOneField
# and therefore using the exact same primary key as the Team model.
class TeamCoreEventsConfig(models.Model):
    """
    Team-level configuration for unified core events.

    Core events are reusable event definitions that can be shared across
    Marketing analytics, Customer analytics, and Revenue analytics.
    """

    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    # Mangled field: we validate the schema via getter/setter
    _core_events = models.JSONField(default=list, db_column="core_events", null=True, blank=True)

    class Meta:
        verbose_name = "Team Core Events Config"
        verbose_name_plural = "Team Core Events Configs"

    @property
    def core_events(self) -> list[dict]:
        """Get the list of core events."""
        return self._core_events or []

    @core_events.setter
    def core_events(self, value: list[dict] | None) -> None:
        """Set and validate the list of core events."""
        if value is None:
            self._core_events = []
            return

        if not isinstance(value, list):
            raise ValidationError("Core events must be a list")

        for event in value:
            validate_core_event(event)

        self._core_events = value
