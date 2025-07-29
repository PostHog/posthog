from posthog.temporal.salesforce_enrichment.workflow import (
    SalesforceEnrichmentAsyncWorkflow,
    enrich_chunk_activity,
    get_total_account_count_activity,
    cache_all_accounts_activity,
)

WORKFLOWS = [
    SalesforceEnrichmentAsyncWorkflow,
]

ACTIVITIES = [
    enrich_chunk_activity,
    get_total_account_count_activity,
    cache_all_accounts_activity,
]
