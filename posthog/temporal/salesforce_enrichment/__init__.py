from posthog.temporal.salesforce_enrichment.conversations_slack_workflow import (
    SalesforceConversationsSlackEnrichmentWorkflow,
    aggregate_conversations_slack_signals_activity,
    enrich_conversations_slack_page_activity,
)
from posthog.temporal.salesforce_enrichment.stripe_workflow import (
    SalesforceStripeEnrichmentWorkflow,
    commit_stripe_watermark_activity,
    enrich_stripe_page_activity,
    get_stripe_watermark_activity,
)
from posthog.temporal.salesforce_enrichment.usage_workflow import (
    SalesforceUsageEnrichmentWorkflow,
    aggregate_usage_signals_activity,
    cache_org_mappings_activity,
    enrich_org_page_activity,
)
from posthog.temporal.salesforce_enrichment.workflow import (
    SalesforceEnrichmentAsyncWorkflow,
    cache_all_accounts_activity,
    enrich_chunk_activity,
)

WORKFLOWS = [
    SalesforceEnrichmentAsyncWorkflow,
    SalesforceUsageEnrichmentWorkflow,
    SalesforceStripeEnrichmentWorkflow,
    SalesforceConversationsSlackEnrichmentWorkflow,
]

ACTIVITIES = [
    enrich_chunk_activity,
    cache_all_accounts_activity,
    aggregate_usage_signals_activity,
    cache_org_mappings_activity,
    enrich_org_page_activity,
    get_stripe_watermark_activity,
    commit_stripe_watermark_activity,
    enrich_stripe_page_activity,
    aggregate_conversations_slack_signals_activity,
    enrich_conversations_slack_page_activity,
]
