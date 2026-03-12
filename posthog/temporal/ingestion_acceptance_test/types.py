"""Types for ingestion acceptance test workflow."""

from pydantic import BaseModel


class IngestionAcceptanceTestInput(BaseModel):
    """Input for the ingestion acceptance test workflow.

    Currently empty as no configuration is needed, but follows the standard
    pattern for Temporal workflows to allow future extensibility.
    """

    pass
