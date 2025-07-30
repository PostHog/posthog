from posthog.temporal.salesforce_enrichment.workflow import (
    SalesforceEnrichmentAsyncWorkflow,
    enrich_chunk_activity,
    cache_all_accounts_activity,
)

WORKFLOWS = [
    SalesforceEnrichmentAsyncWorkflow,
]

ACTIVITIES = [
    enrich_chunk_activity,
    cache_all_accounts_activity,
]
