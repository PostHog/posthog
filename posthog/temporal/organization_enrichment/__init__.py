from posthog.temporal.organization_enrichment.workflow import (
    OrganizationEnrichmentWorkflow,
    enrich_organization_chunk_activity,
)

WORKFLOWS = [OrganizationEnrichmentWorkflow]

ACTIVITIES = [enrich_organization_chunk_activity]
