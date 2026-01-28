"""Input types for ingestion acceptance test workflow."""

from dataclasses import dataclass


@dataclass
class IngestionAcceptanceTestInputs:
    """Inputs for the ingestion acceptance test workflow.

    All configuration is loaded from environment variables by the activity,
    so this is intentionally minimal.
    """

    pass
