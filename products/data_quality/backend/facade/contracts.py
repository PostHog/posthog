"""
Contract types for data_quality.

Frozen, framework-free values other products need. No Django imports.
"""

from dataclasses import dataclass, field
from typing import Any

# The registered name of the check-suite workflow. Lives here rather than in ``facade.temporal`` so
# a caller in another product (data_modeling's DAG workflow) can start the suite by name without
# importing this product's workflow and activity modules.
CHECK_SUITE_WORKFLOW_NAME = "data-quality-run-suite"


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
