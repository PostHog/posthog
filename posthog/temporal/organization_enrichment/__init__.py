from posthog.temporal.organization_enrichment.workflow import (
    OrganizationEnrichmentWorkflow,
    count_organizations_activity,
    enrich_organization_chunk_activity,
)

WORKFLOWS = [OrganizationEnrichmentWorkflow]

ACTIVITIES = [count_organizations_activity, enrich_organization_chunk_activity]
