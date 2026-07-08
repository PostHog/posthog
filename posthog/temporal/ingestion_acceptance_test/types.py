"""Types for ingestion acceptance test workflow."""

from pydantic import BaseModel


class IngestionAcceptanceTestInput(BaseModel):
    """Input for the ingestion acceptance test workflow.

    The lane selects which ingestion routing the run targets (e.g. "main",
    "turbo"). Each lane resolves its own api_host, team_id and project_api_key
    from the worker environment. When lane is None the run falls back to the
    flat INGESTION_ACCEPTANCE_TEST_* env vars (the pre-lane behavior).
    """

    lane: str | None = None
