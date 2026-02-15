import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, field_validator

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

# RE2-incompatible patterns that would work in PostgreSQL but fail in ClickHouse
RE2_INCOMPATIBLE_PATTERNS = [
    (r"\\(\d+)", "backreferences"),
    (r"\(\?[=!<]", "lookahead/lookbehind assertions"),
    (r"\(\?\(", "conditional patterns"),
]


class CleanupPropertyDefinitionsInput(BaseModel):
    """Input for the cleanup property definitions workflow.

    Note: The pattern must be compatible with both PostgreSQL regex and ClickHouse RE2.
    RE2 does not support backreferences, lookahead/lookbehind, or conditional patterns.
    Simple patterns like `^temp_.*` or `_test$` work in both engines.
    """

    team_id: int
    pattern: str
    property_type: PropertyTypeName
    dry_run: bool = False
    batch_size: int = Field(default=5000, gt=0, le=5000)

    @field_validator("pattern")
    @classmethod
    def validate_pattern_compatibility(cls, v: str) -> str:
        # Validate it's a valid regex
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}")

        # Check for RE2-incompatible features
        for incompatible_pattern, feature_name in RE2_INCOMPATIBLE_PATTERNS:
            if re.search(incompatible_pattern, v):
                raise ValueError(
                    f"Pattern uses {feature_name} which is not supported by ClickHouse RE2. "
                    f"Use simple patterns compatible with both PostgreSQL and RE2."
                )

        return v

    def get_property_type_int(self) -> int:
        """Convert the string property type to its integer value."""
        return PROPERTY_TYPE_MAP[self.property_type]


@dataclass
class DeletePostgresPropertyDefinitionsInput:
    """Input for deleting property definitions from PostgreSQL."""

    team_id: int
    pattern: str
    property_type: int
    batch_size: int = 5000


@dataclass
class DeleteClickHousePropertyDefinitionsInput:
    """Input for deleting property definitions from ClickHouse."""

    team_id: int
    pattern: str
    property_type: int


@dataclass
class PreviewPropertyDefinitionsInput:
    """Input for previewing property definitions that would be deleted."""

    team_id: int
    pattern: str
    property_type: int
    limit: int = 100


class CleanupPropertyDefinitionsError(Exception):
    """Error during property definitions cleanup."""

    pass
