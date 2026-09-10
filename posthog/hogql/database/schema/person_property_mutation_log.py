from typing import TYPE_CHECKING

from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringJSONDatabaseField,
    Table,
    UUIDDatabaseField,
)
from posthog.hogql.errors import QueryError

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext


class PersonPropertyMutationLogTable(Table):
    description: str = "Person property updates submitted with events, with a 30-day storage TTL. Query separately by event_uuid; joins are not supported."
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "event_uuid": UUIDDatabaseField(
            name="event_uuid", nullable=False, description="UUID of the event that submitted these updates."
        ),
        "properties": StringJSONDatabaseField(
            name="properties",
            nullable=False,
            description="Original $set, $set_once and $unset payloads. These describe submitted updates, not confirmed profile changes.",
        ),
        "ingested_at": DateTimeDatabaseField(
            name="ingested_at",
            nullable=False,
            description="Kafka message timestamp in UTC; starts the 30-day retention period.",
        ),
    }

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        if context.restricted_properties:
            from products.event_definitions.backend.models.property_definition import (
                PropertyDefinition,  # noqa: PLC0415 — keep Django models off the HogQL import path
            )

            if any(prop.property_type == PropertyDefinition.Type.PERSON for prop in context.restricted_properties):
                raise QueryError("Person property mutation logs are unavailable when person properties are restricted.")
        return "person_property_mutation_log"

    def to_printed_hogql(self) -> str:
        return "person_property_mutation_log"
