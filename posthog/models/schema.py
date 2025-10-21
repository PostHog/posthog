from django.db import models
from django.utils import timezone

from posthog.models.event_definition import EventDefinition
from posthog.models.property_definition import PropertyType
from posthog.models.team import Team
from posthog.models.utils import UUIDTModel


class SchemaPropertyGroup(UUIDTModel):
    """
    A reusable group of properties that defines a schema.
    Can be attached to multiple events via EventSchema.
    """

    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="schema_property_groups",
        related_query_name="schema_property_group",
    )
    project = models.ForeignKey("Project", on_delete=models.CASCADE, null=True)
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_schema_property_groups",
    )

    class Meta:
        indexes = [
            models.Index(fields=["team", "name"], name="schema_pg_team_name_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                name="unique_schema_property_group_team_name",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name} / {self.team.name}"


class SchemaPropertyGroupProperty(UUIDTModel):
    """
    Individual property within a property group.
    Defines the expected name, type, and whether it's required.
    """

    property_group = models.ForeignKey(
        SchemaPropertyGroup,
        on_delete=models.CASCADE,
        related_name="properties",
        related_query_name="property",
    )
    name = models.CharField(max_length=400)
    property_type = models.CharField(max_length=50, choices=PropertyType.choices)
    is_required = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["property_group", "name"],
                name="schema_pgp_group_name_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["property_group", "name"],
                name="unique_property_group_property_name",
            ),
            models.CheckConstraint(
                name="property_type_is_valid_schema",
                check=models.Q(property_type__in=PropertyType.values),
            ),
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        required_str = " (required)" if self.is_required else ""
        return f"{self.name} ({self.property_type}){required_str} / {self.property_group.name}"


class EventSchema(UUIDTModel):
    """
    Associates a property group with an event definition.
    Defines which property groups an event should have.
    """

    event_definition = models.ForeignKey(
        EventDefinition,
        on_delete=models.CASCADE,
        related_name="schemas",
        related_query_name="schema",
    )
    property_group = models.ForeignKey(
        SchemaPropertyGroup,
        on_delete=models.CASCADE,
        related_name="event_schemas",
        related_query_name="event_schema",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event_definition", "property_group"],
                name="unique_event_schema",
            )
        ]

    def __str__(self) -> str:
        return f"{self.event_definition.name} → {self.property_group.name}"
