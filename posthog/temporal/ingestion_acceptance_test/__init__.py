"""Ingestion acceptance test Temporal workflow.

This workflow runs acceptance tests against the PostHog ingestion pipeline
to verify that events can be captured and queried successfully.
"""

from posthog.temporal.ingestion_acceptance_test.activities import run_ingestion_acceptance_tests
from posthog.temporal.ingestion_acceptance_test.workflows import IngestionAcceptanceTestWorkflow

WORKFLOWS = [IngestionAcceptanceTestWorkflow]
ACTIVITIES = [run_ingestion_acceptance_tests]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
]
