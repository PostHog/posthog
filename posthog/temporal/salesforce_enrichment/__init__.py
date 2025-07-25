from posthog.temporal.salesforce_enrichment.workflow import (
    SalesforceEnrichmentWorkflow,
    SalesforceEnrichmentAsyncWorkflow,
    enrich_chunk_activity,
    enrich_chunk_activity_async,
    get_total_account_count_activity,
    cache_all_accounts_activity,
)

WORKFLOWS = [
    SalesforceEnrichmentWorkflow,
    SalesforceEnrichmentAsyncWorkflow,
]

ACTIVITIES = [
    enrich_chunk_activity,
    enrich_chunk_activity_async,
    get_total_account_count_activity,
    cache_all_accounts_activity,
]
