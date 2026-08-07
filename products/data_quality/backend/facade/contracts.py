"""
Contract types for data_quality.

Frozen, framework-free values other products need. No Django imports.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CheckTypeInfo:
    """One entry of the check-type catalog, so a caller can author config without guessing.

    Carries what the registry knows about a type, flattened to plain values -- the spec object
    itself stays internal, since it is a compiler, not data.
    """

    check_type: str
    description: str
    requires_column: bool
    config_schema: dict[str, Any] = field(default_factory=dict)
