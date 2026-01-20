from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from posthog.models.property_definition import PropertyDefinition

# String type names for the workflow input (user-friendly)
PropertyTypeName = Literal["event", "person", "group", "session"]

# Mapping from string names to integer values (matches PropertyDefinition.Type)
PROPERTY_TYPE_MAP: dict[PropertyTypeName, int] = {
    "event": PropertyDefinition.Type.EVENT,
    "person": PropertyDefinition.Type.PERSON,
    "group": PropertyDefinition.Type.GROUP,
    "session": PropertyDefinition.Type.SESSION,
}


class CleanupPropertyDefinitionsInput(BaseModel):
    """Input for the cleanup property definitions workflow."""

    team_id: int
    pattern: str
    property_type: PropertyTypeName
    dry_run: bool = False

    def get_property_type_int(self) -> int:
        """Convert the string property type to its integer value."""
        return PROPERTY_TYPE_MAP[self.property_type]


@dataclass
class DeletePostgresPropertyDefinitionsInput:
    """Input for deleting property definitions from PostgreSQL."""

    team_id: int
    pattern: str
    property_type: int


@dataclass
class DeleteClickHousePropertyDefinitionsInput:
    """Input for deleting property definitions from ClickHouse."""

    team_id: int
    pattern: str
    property_type: int


class CleanupPropertyDefinitionsError(Exception):
    """Error during property definitions cleanup."""

    pass
