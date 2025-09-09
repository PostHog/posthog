from posthog.temporal.salesforce_enrichment.workflow import (
    SalesforceEnrichmentAsyncWorkflow,
    cache_all_accounts_activity,
    enrich_chunk_activity,
)

WORKFLOWS = [
    SalesforceEnrichmentAsyncWorkflow,
]

ACTIVITIES = [
    enrich_chunk_activity,
    cache_all_accounts_activity,
]
