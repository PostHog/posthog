from posthog.temporal.salesforce_enrichment.usage_workflow import (
    SalesforceUsageEnrichmentWorkflow,
    aggregate_usage_signals_activity,
    cache_org_mappings_activity,
    fetch_salesforce_org_ids_activity,
    update_salesforce_usage_activity,
)
from posthog.temporal.salesforce_enrichment.workflow import (
    SalesforceEnrichmentAsyncWorkflow,
    cache_all_accounts_activity,
    enrich_chunk_activity,
)

WORKFLOWS = [
    SalesforceEnrichmentAsyncWorkflow,
    SalesforceUsageEnrichmentWorkflow,
]

ACTIVITIES = [
    enrich_chunk_activity,
    cache_all_accounts_activity,
    aggregate_usage_signals_activity,
    cache_org_mappings_activity,
    fetch_salesforce_org_ids_activity,
    update_salesforce_usage_activity,
]
